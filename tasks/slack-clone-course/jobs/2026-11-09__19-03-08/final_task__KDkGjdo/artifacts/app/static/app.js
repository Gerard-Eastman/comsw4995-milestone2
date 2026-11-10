(()=>{
let token=localStorage.getItem('huddle.token')||''; window.__huddle_token=token;
let me=null, ws=null, channels=[], current=null, workspace=null, thread=null;
const $=s=>document.querySelector(s), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(method,path,body){let o={method,headers:{}};if(token)o.headers.Authorization='Bearer '+token;if(body!==undefined){o.headers['Content-Type']='application/json';o.body=JSON.stringify(body)}let r=await fetch(path,o);let d={};try{d=await r.json()}catch{}return {status:r.status,data:d}}
function showAuth(v){$('#auth-modal').hidden=!v;$('#app').hidden=v}
function err(form,msg){let x=form.querySelector('[role=alert]');if(x)x.textContent=msg||''}
async function boot(){
 let q=new URLSearchParams(location.search);if(q.get('token')){token=q.get('token');localStorage.setItem('huddle.token',token);window.__huddle_token=token}
 if(!token){showAuth(true);return}
 let r=await api('GET','/api/auth/me');if(r.status!==200){token='';localStorage.removeItem('huddle.token');showAuth(true);return}
 me=r.data.user;showAuth(false);await loadWorkspace()
}
async function loadWorkspace(){
 let cu=document.querySelector('[data-testid=current-user]');if(cu)cu.textContent=me?(me.username||me.display_name||''):'';
 let r=await api('GET','/api/workspaces');if(r.status!==200)return;
 if(!r.data.workspaces.length){$('[data-testid=empty-state-create-workspace]').hidden=false;return}
 workspace=r.data.workspaces[0];$('[data-testid=empty-state-create-workspace]').hidden=true;$('.ws-name').textContent=workspace.name;let wh=document.querySelector('[data-testid=workspace-header] .ws-name');if(wh)wh.textContent=workspace.name;let cu2=document.querySelector('[data-testid=current-user]');if(cu2)cu2.textContent=me.username||me.display_name||'';
 let d=await api('GET','/api/workspaces/'+workspace.slug);channels=d.data.channels||[];renderChannels();if(channels[0])selectChannel(channels[0].id)
}
function renderChannels(){let ul=$('[data-testid=channel-list]');ul.innerHTML='';channels.forEach(c=>{let li=document.createElement('li');li.dataset.testid='channel-entry';li.dataset.channelId=c.id;li.dataset.channelName=c.name;li.textContent='# '+c.name;li.onclick=()=>selectChannel(c.id);ul.appendChild(li)})}
async function selectChannel(id){
 current=channels.find(c=>String(c.id)===String(id));if(!current)return;
 $('[data-testid=channel-title]').textContent='#'+current.name;$('[data-testid=channel-topic]').textContent=current.topic||'';let r=await api('GET','/api/channels/'+id+'/messages');renderMessages((r.data.messages||[]).reverse());
}
function renderMessages(ms){let box=$('[data-testid=message-list]');box.innerHTML='';if(!ms.length){box.textContent='No messages yet. Say hi!';return}ms.forEach(m=>box.appendChild(renderMessage(m)))}
function renderMessage(m){
 let d=document.createElement('div');d.dataset.testid='message';d.dataset.messageId=m.id;d.innerHTML=`<span class="avatar">${esc((m.author?.display_name||'?')[0])}</span><span class="author">${esc(m.author?.display_name||'')}</span><time datetime="${m.created_at}">${new Date(m.created_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}</time><div data-testid="message-body">${esc(m.body)}</div>${m.edited_at?'<span class="edited">(edited)</span>':''}${m.reply_count?`<button class="reply-count">${m.reply_count} ${m.reply_count==1?'reply':'replies'}</button>`:''}<div class="toolbar"><button data-testid="open-thread-btn">Thread</button><button data-testid="reaction-button">😊</button><button data-action="edit">Edit</button><button data-action="delete">Delete</button></div><div class="reactions"></div>`;
 d.querySelector('[data-testid=open-thread-btn]').onclick=()=>openThread(m.id);
 d.querySelector('[data-action=edit]').onclick=()=>editRow(d,m);
 d.querySelector('[data-action=delete]').onclick=async()=>{await api('DELETE','/api/messages/'+m.id);await selectChannel(current.id)}
 d.querySelector('[data-testid=reaction-button]').onclick=()=>picker(d,m);
 (m.reactions||[]).forEach(x=>addChip(d,m,x));
 return d
}
function editRow(row,m){let b=row.querySelector('[data-testid=message-body]'),i=document.createElement('input');i.name='edit-body';i.value=m.body;b.replaceWith(i);i.focus();let save=async()=>{if(i.value.trim()){await api('PATCH','/api/messages/'+m.id,{body:i.value});await selectChannel(current.id)}};i.onkeydown=e=>{if(e.key==='Enter')save();if(e.key==='Escape')selectChannel(current.id)}}
function picker(row,m){let p=document.createElement('div');p.dataset.testid='emoji-picker';['👍','❤️','😂','🎉','🚀','👏','🔥','✅'].forEach(e=>{let b=document.createElement('button');b.dataset.testid='emoji-option';b.textContent=e;b.onclick=async()=>{await api('POST','/api/messages/'+m.id+'/reactions',{emoji:e});p.remove();await selectChannel(current.id)};p.appendChild(b)});row.appendChild(p)}
function addChip(row,m,x){let b=document.createElement('button');b.dataset.testid='reaction-chip';b.textContent=x.emoji+' '+x.count;b.onclick=async()=>{await api('DELETE','/api/messages/'+m.id+'/reactions/'+encodeURIComponent(x.emoji));await selectChannel(current.id)};row.querySelector('.reactions').appendChild(b)}
async function openThread(id){thread=id;$('[data-testid=thread-panel]').hidden=false;let r=await api('GET','/api/messages/'+id+'/replies');let box=$('.thread-messages');box.innerHTML='';let p=(await api('GET','/api/channels/'+current.id+'/messages')).data.messages.find(x=>String(x.id)===String(id));if(p)box.innerHTML='<div>'+esc(p.body)+'</div>';(r.data.replies||[]).forEach(x=>{let z=document.createElement('div');z.textContent=x.body;box.appendChild(z)})}
document.addEventListener('DOMContentLoaded',()=>{
 let af=$('[data-testid=auth-form]');$('[data-testid=auth-toggle]').onclick=()=>{let signup=af.dataset.mode==='login';af.dataset.mode=signup?'signup':'login';$('.auth-title').textContent=signup?'Create account':'Log in to Huddle';$('[name=display_name]').hidden=!signup;$('[data-testid=auth-submit]').textContent=signup?'Sign up':'Log in'};
 af.querySelector('[name=display_name]').hidden=true; af.onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(af));let r=await api('POST',af.dataset.mode==='signup'?'/api/auth/register':'/api/auth/login',d);if(r.status>=400){err(af,r.data.error);return}token=r.data.token;localStorage.setItem('huddle.token',token);window.__huddle_token=token;me=r.data.user;showAuth(false);await loadWorkspace()};
 $('[data-testid=workspace-create-form]').onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(e.target)),r=await api('POST','/api/workspaces',d);if(r.status!==201){err(e.target,r.data.error);return}await loadWorkspace()};
 $('[data-testid=new-channel-btn]').onclick=()=>$('#create-channel-modal').hidden=false;$('[data-testid=create-channel-cancel]').onclick=()=>$('#create-channel-modal').hidden=true;
 $('[data-testid=create-channel-form]').onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(e.target));d.is_private=!!e.target.is_private.checked;let r=await api('POST','/api/workspaces/'+workspace.slug+'/channels',d);if(r.status!==201){err(e.target,r.data.error);return}$('#create-channel-modal').hidden=true;channels.push(r.data.channel);renderChannels();selectChannel(r.data.channel.id)};
 $('.composer').onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=message-input]');if(!i.value.trim())return;await api('POST','/api/channels/'+current.id+'/messages',{body:i.value});i.value='';await selectChannel(current.id)};
 $('[data-testid=close-thread]').onclick=()=>$('[data-testid=thread-panel]').hidden=true;
 $('[data-testid=thread-send]').closest('form').onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=thread-input]');if(i.value.trim()){await api('POST','/api/channels/'+current.id+'/messages',{body:i.value,parent_id:thread});i.value='';await openThread(thread);await selectChannel(current.id)}};
 $('[data-testid=logout-btn]').onclick=()=>{localStorage.removeItem('huddle.token');token='';showAuth(true)};
 setInterval(()=>{if(token&&current&&!document.hidden)selectChannel(current.id)},800);
 boot()
});
})()
