import {validateSourceVersion} from './versioning.js';

export function automaticKey(sources,controller) {
  validateSourceVersion(sources);
  for(const pin of [sources.sukisu_commit,sources.susfs_commit,controller.sha])
    if(!/^[0-9a-f]{40}$/.test(pin))throw new Error('Unvollständiger automatischer Quellenauftrag.');
  return [controller.ref,controller.sha,sources.channel,sources.sukisu_commit,sources.susfs_commit,controller.revision||'hidden-name-readdir-v2'].join(':');
}

export class AutomaticBuilder {
  constructor(storage,now=()=>Date.now()) {this.storage=storage;this.now=now;this.busy=false;}
  read() {try{return JSON.parse(this.storage.getItem('center-auto-attempt')||'null');}catch{return null;}}
  save(value) {this.storage.setItem('center-auto-attempt',JSON.stringify(value));}
  async ensure(api,sources,controller,canSubmit=()=>true) {
    if(this.busy)return {outcome:'busy'};
    if(!api.token||controller.protocol!==2||!controller.automatic)return {outcome:'disabled'};
    this.busy=true;
    try {
      const key=automaticKey(sources,controller);
      const runs=await api.runs(controller.ref);
      const active=runs.find(r=>r.head_branch===controller.ref&&r.status!=='completed');
      if(active)return {outcome:'waiting',run:active};
      const release=await api.currentRelease(sources,controller.revision);
      if(release)return {outcome:'current',release};
      const previous=this.read();
      if(previous?.key===key)return {outcome:'attempted',attempt:previous,
        run:runs.find(r=>r.display_title?.includes(previous.id))||null};
      const failed=await api.recentFailure(sources,controller,this.now());
      if(failed)return {outcome:'cooldown',run:failed};
      if(!canSubmit())return {outcome:'changed'};
      const id=crypto.randomUUID(),time=this.now();
      const attempt={key,id,time,ref:controller.ref,repo:api.repo,state:'submitting'};
      // Persist before POST. A reload or ambiguous network failure must not
      // silently create a second submission. GitHub's independent timer can
      // continue checking even while this app is closed.
      this.save(attempt);
      try {
        const result=await api.dispatch(controller.ref,sources.channel,false,
          {sources,controllerSha:controller.sha,requestId:id,canSubmit});
        if(result!==id)throw new Error('Build-Auftragskennung wurde nicht bestätigt.');
        this.save({...attempt,state:'submitted'});
        return {outcome:'submitted',pending:{id,time,ref:controller.ref,repo:api.repo}};
      } catch(error) {
        this.save({...attempt,state:'unconfirmed'});throw error;
      }
    } finally {this.busy=false;}
  }
}
