import {readVersionFormula, versionCode, validateSourceVersion} from './versioning.js';

export const GH = 'https://api.github.com';
// Stable official repository identity survives the Ultra -> Nova rename.
export const SUKI = `${GH}/repositories/957055748`;
export const SUS = 'https://gitlab.com/api/v4/projects/simonpunk%2Fsusfs4ksu/repository';
const shaPattern = /^[0-9a-f]{40}$/;
const profile = 'S928BXXS6EZJ1-EUX-android14-6.1.162';

function decodeFile(file) {
  if (file.encoding !== 'base64' || typeof file.content !== 'string')
    throw new Error('Build-Controller konnte nicht gelesen werden.');
  return new TextDecoder('utf-8', {fatal:true}).decode(Uint8Array.from(atob(file.content.replace(/\s/g,'')), c=>c.charCodeAt(0)));
}

async function sha256(text) {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(hash), b=>b.toString(16).padStart(2,'0')).join('');
}

function sourceRequest(sources, channel, controllerSha) {
  if (!['main','release'].includes(channel) || sources?.channel !== channel)
    throw new Error('Update-Kanal und geprüfte Quellen stimmen nicht überein. Updates erneut prüfen.');
  if (!shaPattern.test(sources.sukisu_commit) || !shaPattern.test(sources.susfs_commit)
      || !shaPattern.test(controllerSha))
    throw new Error('Quellen und Versionsberechnung konnten nicht bestätigt werden. Updates erneut prüfen.');
  validateSourceVersion(sources);
  return {schema:1,channel,sukisu_commit:sources.sukisu_commit,sukisu_code:sources.sukisu_code,
    sukisu_count:sources.sukisu_count,susfs_commit:sources.susfs_commit,controller_sha:controllerSha,
    ...(sources.sukisu_version_formula?{sukisu_version_formula:sources.sukisu_version_formula}:{})};
}

function controllerMatches(controller, sources) {
  if (controller.protocol !== 2) return workflowMatches(controller.content,sources);
  if (!controller.channels.includes(sources.channel)) return false;
  if (sources.sukisu_version_formula && (sources.sukisu_version_formula.base!==40000
      || sources.sukisu_version_formula.offset!==2815 || sources.sukisu_version_formula.operation!=='-')
      && controller.versionScheme!=='kbuild-affine-v1') return false;
  sourceRequest(sources,sources.channel,controller.sha);
  return true;
}

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

export function workflowMatches(text, sources) {
  if (sources.channel && sources.channel !== 'main') return false;
  // Match resolver arguments rather than labels or commented examples.
  const args = [...text.matchAll(/^\s*ARGS\+=\(([^\r\n)]+)\)\s*$/gm)].map(m=>m[1]).join(' ');
  const pin = args.match(/--expected-main-commit\s+([0-9a-f]{40})(?![0-9a-f])/i)?.[1];
  const code = args.match(/--expected-main-code\s+(\d+)/)?.[1];
  const sus = args.match(/--expected-susfs-commit\s+([0-9a-f]{40})(?![0-9a-f])/i)?.[1];
  return Boolean(pin && code && sus && pin === sources.sukisu_commit
    && Number(code) === sources.sukisu_code && sus === sources.susfs_commit);
}

export function runOutcome(run, jobs = [], artifacts = []) {
  if (run.status !== 'completed') return {text:({in_progress:'LÄUFT',queued:'IN WARTESCHLANGE',waiting:'WARTET',pending:'VORGEMERKT',requested:'ANGEFORDERT'})[run.status] || run.status,className:'running'};
  if (run.conclusion === 'success') {
    if (selectKernelArtifact(artifacts,run)) return {text:'KERNEL-ZIP BEREIT',className:''};
    const skipped = jobs.some(j => /Kernel|SukiSU 6\.1/.test(j.name) && j.conclusion === 'skipped');
    return {text:skipped?'KEIN KERNEL GEBAUT':'KEINE KERNEL-ZIP',className:'neutral'};
  }
  return {text:({failure:'FEHLGESCHLAGEN',cancelled:'ABGEBROCHEN',skipped:'ÜBERSPRUNGEN',timed_out:'ZEITLIMIT',startup_failure:'STARTFEHLER'})[run.conclusion] || run.conclusion,className:'bad'};
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

export function releaseMatchesSources(release,sources,revision='hidden-name-readdir-v2') {
  const tag=sources.release_tag+(revision?'-'+revision:'');
  const body=release.body||'',assets=release.assets||[];
  return !release.draft && (release.tag_name===tag || (release.tag_name?.startsWith(tag+'-r')&&/^\d+$/.test(release.tag_name.slice(tag.length+2))))
    && body.includes('SukiSU commit: '+sources.sukisu_commit) && body.includes('SuSFS commit: '+sources.susfs_commit)
    && assets.some(a=>a.name==='build-plan.json')
    && assets.some(a=>a.name?.endsWith('AnyKernel3.zip')&&a.name.includes('S928BXXS6EZJ1-EUX')&&/^sha256:[0-9a-f]{64}$/.test(a.digest||''));
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
    const repository=(await this.call(SUKI)).data;
    if(repository?.id!==957055748||!/^[-\w.]+\/[-\w.]+$/.test(repository.full_name||''))
      throw new Error('Offizielle SukiSU-Projektidentität konnte nicht bestätigt werden.');
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
    const formula=readVersionFormula(build),code=versionCode(count,formula);
    const susCommit = (await this.call(`${SUS}/commits/gki-android14-6.1`)).data;
    if (!shaPattern.test(susCommit.id)) throw new Error('Ungültige SuSFS-Commit-ID.');
    const header = (await this.call(`${SUS}/files/kernel_patches%2Finclude%2Flinux%2Fsusfs.h?ref=${susCommit.id}`)).data;
    const version = atob(header.content.replace(/\s/g, '')).match(/^#define\s+SUSFS_VERSION\s+"(v[\w.+-]+)"/m)?.[1];
    if (!version) throw new Error('SuSFS-Version konnte nicht gelesen werden.');
    const manager = release.assets.find(a => a.name.endsWith('.apk') && a.name.includes(`_${code}-`)) || null;
    return {sukisu_commit: pin, sukisu_code: code, sukisu_count: count, sukisu_tag: release.tag_name,
      sukisu_message: commit.commit.message.split('\n')[0], channel,sukisu_version_formula:formula,
      sukisu_repository:repository.full_name,sukisu_repository_id:957055748,
      susfs_commit: susCommit.id, susfs_version: version, susfs_message: susCommit.title,
      manager, release_tag: `s928b-ezj1-suki${code}-susfs${version.replace(/^v/, '')}-${pin.slice(0,8)}-${susCommit.id.slice(0,8)}`,
      susfs_source_url: `https://gitlab.com/simonpunk/susfs4ksu/-/archive/${susCommit.id}/susfs4ksu-${susCommit.id}.zip`};
  }
  async resolveWorkflowRef(ref) {
    if (typeof ref !== 'string' || !ref.trim() || ref.trim().length > 200 || /[\x00-\x1f\x7f]/.test(ref))
      throw new Error('Gültigen Workflow-Branch eingeben, zum Beispiel main.');
    const name = ref.trim();
    let sha;
    try {
      const commit = await this.data(`/commits/${encodeURIComponent(name)}`);
      if (!shaPattern.test(commit?.sha)) throw new Error('Workflow-Branch konnte nicht bestätigt werden. Verbindung erneut prüfen.');
      sha = commit.sha;
    } catch (error) {
      if (error.status === 404 || error.status === 422) {
        const missing = new Error(`Workflow-Branch „${name}“ existiert in ${this.repo} nicht. Einen vorhandenen Branch wie main eintragen; hier gehört kein Benutzername hin.`);
        missing.status=error.status;throw missing;
      }
      throw error;
    }
    return {ref:name,sha};
  }
  async validateWorkflowRef(ref) { return (await this.resolveWorkflowRef(ref)).ref; }
  async workflowController(ref) {
    const controller = await this.resolveWorkflowRef(ref);
    const file = await this.data(`/contents/.github/workflows/build-center.yml?ref=${controller.sha}`);
    const content = decodeFile(file);
    if (!/^  BUILD_CENTER_PROTOCOL: ['"]?2['"]?\s*$/m.test(content)) return {...controller,content,protocol:1};
    // Read every contract component at the same immutable controller commit.
    const [manifestFile,resolverFile] = await Promise.all([
      this.data(`/contents/build-center/controller.json?ref=${controller.sha}`),
      this.data(`/contents/build-center/ci/check_updates.py?ref=${controller.sha}`)
    ]);
    let manifest;
    try { manifest=JSON.parse(decodeFile(manifestFile)); }
    catch { throw new Error('Build-Controller-Manifest ist ungültig.'); }
    if (manifest.schema !== 2 || manifest.workflow !== 'build-center.yml'
        || manifest.source_binding !== 'source-request-v1' || manifest.profile !== profile
        || !Array.isArray(manifest.channels) || !manifest.channels.length
        || manifest.channels.some(c=>!['main','release'].includes(c))
        || manifest.workflow_sha256 !== await sha256(content)
        || manifest.resolver_sha256 !== await sha256(decodeFile(resolverFile)))
      throw new Error('Build-Controller und Manifest passen nicht zusammen. Integration erneut prüfen.');
    return {...controller,content,protocol:2,channels:manifest.channels,
      automatic:manifest.automatic_builds===true,versionScheme:manifest.source_versions,
      revision:manifest.kernel_revision||'hidden-name-readdir-v2'};
  }
  async compatibleController(sources, ref) {
    let configured;
    try { configured=await this.workflowController(ref); }
    catch (error) {
      if (this.repo!=='kaos2310/Super-Builders' || !/^codex\/sukisu-\d+[-\w]*$/.test(ref)
          || ![404,422].includes(error.status)) throw error;
      configured={ref,content:'',protocol:1};
    }
    if (controllerMatches(configured,sources)) return configured;
    // A stable update controller is discoverable before its first Actions run.
    // This also migrates the old version-specific setting saved by APK 1.1.2.
    const preferred = this.repo === 'kaos2310/Super-Builders'
      ? ['codex/build-center-auto-updates','main'].filter(r=>r!==configured.ref) : [];
    for (const branch of preferred) {
      let candidate;
      try { candidate=await this.workflowController(branch); }
      catch (error) { if (error.status===404 || error.status===422) continue; throw error; }
      if (controllerMatches(candidate,sources)) return candidate;
    }
    const runs = await this.runs();
    const version = new RegExp(`\\bSukiSU ${sources.sukisu_code}\\b`);
    const branches = [...new Set(runs.filter(r => r.head_branch !== configured.ref && version.test(r.display_title)
      && (r.status !== 'completed' || r.conclusion === 'success')).map(r => r.head_branch))].slice(0,4);
    const candidates = await Promise.allSettled(branches.map(branch => this.workflowController(branch)));
    const match = candidates.find(r => r.status === 'fulfilled' && controllerMatches(r.value,sources));
    if (match) return match.value;
    throw new Error(`SukiSU ${sources.sukisu_code} erkannt. Der Branch „${configured.ref}“ ist auf ältere Quellen festgelegt. Die automatische Build-Integration muss einmalig veröffentlicht werden; danach übernimmt die App neue Quellstände automatisch.`);
  }
  async installation(ref = 'main', checkRef = true) {
    let workflow;
    try { workflow = await this.data('/actions/workflows/build-center.yml'); }
    catch (error) { if (error.status === 404) return null; throw error; }
    if (workflow.state === 'active' && checkRef) await this.validateWorkflowRef(ref);
    return workflow;
  }
  async dispatch(ref, channel, force = false, expected = null) {
    if (!this.token) throw new Error('Zum Starten einen GitHub-Token mit Actions-Schreibrecht hinterlegen.');
    let request;
    if (expected) {
      const controller = await this.workflowController(ref);
      if (expected.controllerSha && controller.sha !== expected.controllerSha) throw new Error('Build-Controller wurde geändert. Verbindung erneut prüfen.');
      if (!controllerMatches(controller,expected.sources)) throw new Error('Build-Controller und angezeigte Quellen passen nicht zusammen. Updates erneut prüfen.');
      if (controller.protocol === 2) request=sourceRequest(expected.sources,channel,expected.controllerSha);
      ref = controller.ref;
    } else ref = await this.validateWorkflowRef(ref);
    if (expected?.canSubmit && !expected.canSubmit()) throw new Error('Einstellungen wurden während der Prüfung geändert.');
    const requestId = expected?.requestId || crypto.randomUUID();
    if (!/^[A-Za-z0-9._-]{1,100}$/.test(requestId)) throw new Error('Ungültige Build-Auftragskennung.');
    await this.call(`${GH}/repos/${this.repo}/actions/workflows/build-center.yml/dispatches`, 'POST', {
      ref, inputs: {channel, force: String(force), request_id: requestId,
        ...(request ? {source_request:JSON.stringify(request)} : {})}
    });
    return requestId;
  }
  async runs(ref = '') { return (await this.data('/actions/workflows/build-center.yml/runs?per_page=30'+(ref?'&branch='+encodeURIComponent(ref):''))).workflow_runs; }
  async findRun(requestId, ref = '') { return (await this.runs(ref)).find(r => r.display_title.includes(requestId)) || null; }
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
  async currentRelease(sources,revision) {
    return (await this.releases()).find(r=>releaseMatchesSources(r,sources,revision))||null;
  }
  async recentFailure(sources,controller,now=Date.now()) {
    const pair=sources.sukisu_commit.slice(0,8)+'-'+sources.susfs_commit.slice(0,8);
    const response=await this.data('/actions/artifacts?name='+encodeURIComponent('Build-Center-Plan-'+pair)+'&per_page=100');
    const artifacts=(response.artifacts||[]).filter(a=>!a.expired&&a.workflow_run?.id)
      .sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
    if(!artifacts.length)return null;
    const age=now-Date.parse(artifacts[0].created_at);
    if(!Number.isFinite(age)||age<0||age>=86400000)return null;
    const run=await this.run(artifacts[0].workflow_run.id);
    return run.head_sha===controller.sha&&run.status==='completed'&&['failure','timed_out','cancelled'].includes(run.conclusion)?run:null;
  }
}
