export const GH = 'https://api.github.com';
export const SUKI = `${GH}/repos/SukiSU-Ultra/SukiSU-Ultra`;
export const SUS = 'https://gitlab.com/api/v4/projects/simonpunk%2Fsusfs4ksu/repository';
const shaPattern = /^[0-9a-f]{40}$/;

export function assertRepository(value) {
  if (!/^[A-Za-z0-9][\w-]{0,38}\/(?!\.{1,2}$)[\w.-]{1,100}$/.test(value)) throw new Error('Repository als Besitzer/Name eingeben.');
  return value;
}

export function apiError(status, headers = {}, data = {}) {
  if (status === 401) return 'GitHub-Token ungültig oder abgelaufen.';
  if (status === 403 || status === 429) {
    const reset = headers['x-ratelimit-reset'];
    return 'Zugriff verweigert oder API-Limit erreicht.' + (reset ? ` Neuer Versuch ab ${new Date(Number(reset) * 1000).toLocaleTimeString('de-DE')}.` : '');
  }
  if (status === 422) {
    const detail = typeof data?.message === 'string' ? data.message : '';
    if (/No (?:ref|commit) found|Reference does not exist/i.test(detail))
      return 'Workflow-Branch nicht gefunden. Unter GitHub-Verbindung einen vorhandenen Branch eintragen, zum Beispiel main.';
    if (/workflow_dispatch/i.test(detail))
      return 'Der Workflow auf diesem Branch unterstützt keinen manuellen Start. Workflow-Branch und build-center.yml prüfen.';
    if (/Unexpected inputs|Provided value|Required input/i.test(detail))
      return 'GitHub hat die Workflow-Eingaben abgelehnt. App und Workflow müssen denselben Stand verwenden.';
  }
  return ({404: 'Quelle oder Workflow nicht gefunden.', 410: 'Artefakt abgelaufen.',
    422: 'GitHub hat den Auftrag abgelehnt. Branch und Workflow-Eingaben prüfen.'})[status] || `Netzwerkfehler (HTTP ${status}).`;
}

export function selectKernelArtifact(artifacts, run) {
  if (run?.status !== 'completed' || run?.conclusion !== 'success') return null;
  return artifacts.find(a => !a.expired && a.name.endsWith('-Strict-AnyKernel3-Flash')
    && a.name.includes('S928BXXS6EZJ1-EUX') && a.digest?.match(/^sha256:[0-9a-f]{64}$/)
    && String(a.workflow_run?.id ?? run.id) === String(run.id)) || null;
}

export function selectReleaseAssets(releases) {
  // Only Build Center releases carry a manifest generated after the full pipeline.
  return releases.filter(r => !r.draft && r.tag_name?.startsWith('s928b-ezj1-suki')
    && r.assets?.some(a => a.name === 'build-plan.json'));
}

export function selectEzj1ManagerAssets(releases) {
  return releases.filter(r => !r.draft && !r.prerelease).flatMap(r => (r.assets || []).filter(a =>
    /^SukiSU_EZJ1_v.+_\d+-arm64-v8a-release\.apk$/.test(a.name)
    && /^sha256:[0-9a-f]{64}$/.test(a.digest || '')
    && a.browser_download_url?.startsWith('https://github.com/kaos2310/Super-Builders/releases/download/')));
}

export class Github {
  constructor(transport, token = '', repo = 'kaos2310/Super-Builders') {
    this.transport = transport; this.token = token; this.repo = assertRepository(repo);
  }
  async call(url, method = 'GET', data) {
    const token = new URL(url).hostname === 'api.github.com' ? this.token : '';
    const response = await this.transport({url, method, data, token});
    if (response.status < 200 || response.status >= 300) {
      const error = new Error(apiError(response.status, response.headers, response.data));
      error.status = response.status;
      throw error;
    }
    return response;
  }
  async data(path) { return (await this.call(`${GH}/repos/${this.repo}${path}`)).data; }
  async sources(channel = 'main') {
    const release = (await this.call(`${SUKI}/releases/latest`)).data;
    const commit = (await this.call(`${SUKI}/commits/${encodeURIComponent(channel === 'main' ? 'main' : release.tag_name)}`)).data;
    const pin = commit.sha;
    if (!shaPattern.test(pin)) throw new Error('Ungültige SukiSU-Commit-ID.');
    const countResponse = await this.call(`${SUKI}/commits?sha=${pin}&per_page=1`);
    const last = countResponse.headers?.link?.match(/[?&]page=(\d+)[^>]*>; rel="last"/);
    const count = last ? Number(last[1]) : countResponse.data.length;
    if(count < 2815) throw new Error('Vollständige SukiSU-Commitanzahl fehlt in der API-Antwort.');
    const kbuild = (await this.call(`${SUKI}/contents/kernel/Kbuild?ref=${pin}`)).data;
    const build = atob(kbuild.content.replace(/\s/g, ''));
    if (!/^VERSION_BASE\s*:=\s*40000\s*$/m.test(build) || !/^VERSION_OFFSET\s*:=\s*2815\s*$/m.test(build)
      || !build.includes('expr $(VERSION_BASE) + $(LOCAL_COUNT) - $(VERSION_OFFSET)')) {
      throw new Error('SukiSU hat seine Versionsberechnung geändert; Anpassung erforderlich.');
    }
    const code = 40000 + count - 2815;
    const susCommit = (await this.call(`${SUS}/commits/gki-android14-6.1`)).data;
    if (!shaPattern.test(susCommit.id)) throw new Error('Ungültige SuSFS-Commit-ID.');
    const header = (await this.call(`${SUS}/files/kernel_patches%2Finclude%2Flinux%2Fsusfs.h?ref=${susCommit.id}`)).data;
    const version = atob(header.content.replace(/\s/g, '')).match(/^#define\s+SUSFS_VERSION\s+"(v[\w.+-]+)"/m)?.[1];
    if (!version) throw new Error('SuSFS-Version konnte nicht gelesen werden.');
    const manager = release.assets.find(a => a.name.endsWith('.apk') && a.name.includes(`_${code}-`)) || null;
    return {sukisu_commit: pin, sukisu_code: code, sukisu_count: count, sukisu_tag: release.tag_name,
      sukisu_message: commit.commit.message.split('\n')[0], channel,
      susfs_commit: susCommit.id, susfs_version: version, susfs_message: susCommit.title,
      manager, release_tag: `s928b-ezj1-suki${code}-susfs${version.replace(/^v/, '')}-${pin.slice(0,8)}-${susCommit.id.slice(0,8)}`,
      susfs_source_url: `https://gitlab.com/simonpunk/susfs4ksu/-/archive/${susCommit.id}/susfs4ksu-${susCommit.id}.zip`};
  }
  async validateWorkflowRef(ref) {
    if (typeof ref !== 'string' || !ref.trim() || ref.trim().length > 200 || /[\x00-\x1f\x7f]/.test(ref))
      throw new Error('Gültigen Workflow-Branch eingeben, zum Beispiel main.');
    const name = ref.trim();
    try {
      const commit = await this.data(`/commits/${encodeURIComponent(name)}`);
      if (!shaPattern.test(commit?.sha)) throw new Error('Workflow-Branch konnte nicht bestätigt werden. Verbindung erneut prüfen.');
    } catch (error) {
      if (error.status === 404 || error.status === 422)
        throw new Error(`Workflow-Branch „${name}“ existiert in ${this.repo} nicht. Einen vorhandenen Branch wie main eintragen; hier gehört kein Benutzername hin.`);
      throw error;
    }
    return name;
  }
  async installation(ref = 'main') {
    let workflow;
    try { workflow = await this.data('/actions/workflows/build-center.yml'); }
    catch (error) { if (error.status === 404) return null; throw error; }
    if (workflow.state === 'active') await this.validateWorkflowRef(ref);
    return workflow;
  }
  async dispatch(ref, channel, force = false) {
    if (!this.token) throw new Error('Zum Starten einen GitHub-Token mit Actions-Schreibrecht hinterlegen.');
    ref = await this.validateWorkflowRef(ref);
    const requestId = crypto.randomUUID();
    await this.call(`${GH}/repos/${this.repo}/actions/workflows/build-center.yml/dispatches`, 'POST', {
      ref, inputs: {channel, force: String(force), request_id: requestId}
    });
    return requestId;
  }
  async runs() { return (await this.data('/actions/workflows/build-center.yml/runs?per_page=30')).workflow_runs; }
  async findRun(requestId) { return (await this.runs()).find(r => r.display_title.includes(requestId)) || null; }
  async run(id) {
    if (!/^\d+$/.test(String(id))) throw new Error('Ungültige Lauf-ID.');
    return this.data(`/actions/runs/${id}`);
  }
  async artifacts(id) {
    const list = [];
    for (let page = 1; page <= 10; page++) {
      const response = await this.data(`/actions/runs/${id}/artifacts?per_page=100&page=${page}`);
      list.push(...response.artifacts);
      if (response.artifacts.length < 100) return list;
    }
    throw new Error('Zu viele Artefakte; Download direkt bei GitHub öffnen.');
  }
  async jobs(id) { return (await this.data(`/actions/runs/${id}/jobs?per_page=100`)).jobs; }
  async releases() { return this.data('/releases?per_page=30'); }
}
