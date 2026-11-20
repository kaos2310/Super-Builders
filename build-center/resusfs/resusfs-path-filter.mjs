import {bridge,normalizePackages} from './resusfs-runtime.mjs?r=2';
export const CONTROL='/data/adb/modules/ReSuSFS/bin/resusfs-path-filter';
export function parseStatus(value) {
 if(value?.schema!==1||value.owner!=='ReSuSFS'||typeof value.write_allowed!=='boolean'||typeof value.prerequisites_present!=='boolean'||value.command_support_probed!==false||value.kernel_readback_available!==false||typeof value.selection_saved!=='boolean'||typeof value.saved_selection_valid!=='boolean'||typeof value.revision!=='string'||!/^(none|[0-9]+-[0-9]+)$/.test(value.revision)||normalizePackages(value.packages)!==value.packages)throw new Error('SUS_PATH-UID-Status nicht lesbar');
 return value;
}
export function command(state,text) {
 parseStatus(state);
 if(!state.write_allowed||!state.prerequisites_present)throw new Error('Pfadfreigabe ist für diesen Verwalter oder Kernel gesperrt');
 return `${CONTROL} set '${normalizePackages(text)}' '${state.revision}'`;
}
export function mount(container,doc=document,scope=globalThis,run=bridge) {
 const section=doc.createElement('section');section.id='resusfs-path-filter-panel';section.className='rs-priority';
 section.innerHTML=`<h3>SUS_PATH: Pfade für ausgewählte Apps sichtbar lassen</h3><p class="rs-note">Zusätzlicher SUSFS-2.4.0-UID-Filter. Die eingetragenen Apps erhalten eine Ausnahme von der SUS_PATH-Pfadfilterung. Die übrigen Kernel-Regeln bleiben bestehen. Priority UID und die ursprünglichen SUSFS-Regeln bleiben eigenständige Einstellungen.</p><label for="rs-path-packages">Paketnamen, durch Kommas getrennt</label><textarea id="rs-path-packages" rows="2" spellcheck="false" autocapitalize="off" placeholder="com.example.app"></textarea><button type="button" id="rs-path-apply">Pfadfreigabe anwenden &amp; speichern</button><button type="button" id="rs-path-refresh">Status lesen</button><p id="rs-path-status" role="status" aria-live="polite"></p><p class="rs-note">Ohne gespeicherte Auswahl wird beim Start nichts gesetzt. Eine leere Liste entfernt die Freigaben. Die Liste im Kernel kann nicht zurückgelesen werden; angezeigt wird die gespeicherte Auswahl. Ob dieser native Befehl im laufenden Kernel vorhanden ist, bestätigt erst ein ausdrücklich gestarteter Schreibaufruf. Beim Öffnen wird nur gelesen.</p>`;
 container.append(section);const $=id=>section.querySelector(`#${id}`);let state=null,busy=false;
 const render=()=>{$('rs-path-refresh').disabled=busy;$('rs-path-apply').disabled=$('rs-path-packages').disabled=busy||!state?.write_allowed||!state?.prerequisites_present;};
 const refresh=async()=>{if(busy)return;busy=true;render();try{state=parseStatus(JSON.parse(await run(`${CONTROL} status`,scope)));$('rs-path-packages').value=state.packages;$('rs-path-status').textContent=!state.saved_selection_valid?'Die gespeicherte Auswahl ist ungültig; eine neue Auswahl ist erforderlich.':!state.prerequisites_present?'Benötigt SUSFS 2.4.0 mit SUS_PATH; bisherige Regeln bleiben verfügbar.':!state.write_allowed?'Schreibzugriffe pausieren: ReSuSFS muss der aktive SUSFS-Verwalter sein.':state.selection_saved?'Gespeicherte Pfadfreigabe gelesen; keine Kernel-Leseabfrage verfügbar.':'Keine eigene Pfadfreigabe gespeichert; Kernel-Vorgaben bleiben bestehen.';}catch(error){state=null;$('rs-path-status').textContent=error.message;}finally{busy=false;render();}};
 $('rs-path-refresh').addEventListener('click',refresh);
 $('rs-path-apply').addEventListener('click',async()=>{
  let cmd,selected;try{selected=normalizePackages($('rs-path-packages').value);cmd=command(state,selected);}catch(error){$('rs-path-status').textContent=error.message;return;}
  if(!scope.confirm('SUS_PATH-Pfade für diese Apps sichtbar lassen und die Auswahl speichern? Eine leere Liste entfernt alle Freigaben.'))return;
  busy=true;render();try{const result=JSON.parse(await run(cmd,scope));if(result.applied!==true||result.saved!==true||result.kernel_readback_available!==false)throw new Error('Der Kernel hat die Änderung nicht bestätigt');state=parseStatus(JSON.parse(await run(`${CONTROL} status`,scope)));if(state.packages!==selected||state.revision!==result.revision)throw new Error('Die gespeicherte Auswahl wurde inzwischen verändert; Status neu lesen');$('rs-path-packages').value=state.packages;$('rs-path-status').textContent='Schreibaufruf vom Kernel bestätigt und Auswahl gespeichert; keine unabhängige Kernel-Leseabfrage verfügbar.';}catch(error){state=null;$('rs-path-status').textContent=error.message;}finally{busy=false;render();}
 });render();refresh();return{section,refresh};
}
export function integrate(doc=document,scope=globalThis,run=bridge) {
 const ensure=()=>{const opener=doc.getElementById('resusfs-runtime-open');if(opener&&opener.textContent!=='Runtime & UID-Filter →')opener.textContent='Runtime & UID-Filter →';const host=doc.getElementById('resusfs-runtime-panel');if(host&&!doc.getElementById('resusfs-path-filter-panel'))mount(host,doc,scope,run);};
 new MutationObserver(ensure).observe(doc.body,{childList:true,subtree:true});ensure();
}
if(typeof document!=='undefined')integrate();
