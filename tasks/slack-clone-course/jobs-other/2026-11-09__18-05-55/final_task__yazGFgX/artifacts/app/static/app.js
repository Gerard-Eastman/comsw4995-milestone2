const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let uiLock=false; document.addEventListener('mouseover',e=>{if(e.target.closest&&e.target.closest('[data-testid=message]'))uiLock=true}); document.addEventListener('mouseout',e=>{if(e.target.closest&&e.target.closest('[data-testid=message]')&&!document.querySelector('[data-testid=emoji-picker]'))uiLock=false}); let token=localStorage.getItem('huddle.token') || new URLSearchParams(location.search).get('token'), me=null, ws=null, channel=null, messages=[]; if(token) localStorage.setItem('huddle.token',token);
const api=async(path,opt={})=>{opt.headers={...(opt.headers||{}),...(token?{Authorization:'Bearer '+token}:{})};if(opt.body&&typeof opt.body!='string'){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(opt.body)}let r=await fetch('/api'+path,opt),d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||d.message||('HTTP '+r.status));return d};
function err(f,e){let x=f.querySelector('.error,[role=alert]');if(!x){x=document.createElement('div');x.className='error';x.setAttribute('role','alert');f.prepend(x)}x.hidden=false;x.style.display='block';x.textContent=e.message||String(e)}
function showAuth(){ $('#auth-modal').hidden=false; $('#app').style.display='none' }
function showApp(){ $('#auth-modal').hidden=true; $('#app').style.display='grid'; if(me){$('[data-testid=current-user]').textContent=me.username; $('[data-testid=workspace-header] .ws-name').textContent='Huddle'} loadWorkspaces().catch(e=>console.error(e)) }
async function loadWorkspaces(){let d=await api('/workspaces');if(!d.workspaces.length){$('[data-testid=empty-state-create-workspace]').hidden=false;return}ws=d.workspaces[0];$('[data-testid=workspace-header] .ws-name').textContent=ws.name;let x=await api('/workspaces/'+ws.slug);renderChannels(x.channels);if(x.channels[0])selectChannel(x.channels[0])}
function renderChannels(cs){let l=$('[data-testid=channel-list');l.innerHTML='';cs.filter(c=>!c.is_dm).forEach(c=>{let li=document.createElement('li');li.dataset.testid='channel-entry';li.dataset.channelId=c.id;li.dataset.channelName=c.name;li.textContent='#'+c.name;li.onclick=()=>selectChannel(c);l.append(li)})}
async function selectChannel(c,background=false){channel=c;$('[data-testid=channel-title]').textContent='#'+c.name;$('[data-testid=channel-topic]').textContent=c.topic||'';let d=await api('/channels/'+c.id+'/messages');if(background&&uiLock)return;messages=d.messages||[];renderMessages()}
function renderMessages(){
 let l=$('[data-testid=message-list');l.innerHTML='';
 if(!messages.length){l.innerHTML='<div class="empty-copy">No messages yet. Start the conversation.</div>';return}
 messages.slice().reverse().forEach(m=>{
  let row=document.createElement('article');row.dataset.testid='message';row.dataset.messageId=m.id;row.onmouseenter=()=>uiLock=true;row.onmouseleave=()=>{if(!document.querySelector('[data-testid=emoji-picker]'))uiLock=false};row.innerHTML=`<div class="avatar">${(m.author.display_name||m.author.username)[0]}</div><b>${m.author.display_name||m.author.username}</b> <time>${new Date(m.created_at).toLocaleString()}</time><div data-testid="message-body">${m.body}${m.edited_at?' <i class="edited">(edited)</i>':''}</div><div class="toolbar"><button data-action="edit">Edit</button><button data-action="delete">Delete</button><button data-testid="open-thread-btn"><span class="reply-count">${m.reply_count||0} ${(m.reply_count||0)==1?'reply':'replies'}</span></button><button type="button" data-testid="reaction-button">😀</button></div><div class="reactions">${(m.reactions||[]).map(r=>`<button data-testid="reaction-chip" data-emoji="${r.emoji}">${r.emoji} ${r.count}</button>`).join('')}</div>`;
  row.querySelector('[data-testid=open-thread-btn]').onclick=()=>openThread(m);
  row.querySelector('[data-testid=reaction-button]').onclick=()=>showPicker(row,m);
  row.querySelector('[data-action=edit]').onclick=async()=>{let i=document.createElement('input');i.name='edit-body';i.value=m.body;row.querySelector('[data-testid=message-body]').replaceWith(i);i.focus();i.onkeydown=async e=>{if(e.key==='Enter'){uiLock=false;await api('/messages/'+m.id,{method:'PATCH',body:{body:i.value}});await selectChannel(channel)}}};
  row.querySelector('[data-action=delete]').onclick=async()=>{uiLock=false;await api('/messages/'+m.id,{method:'DELETE'});await selectChannel(channel)};
  row.querySelectorAll('[data-testid=reaction-chip]').forEach(b=>b.onclick=async()=>{await api('/messages/'+m.id+'/reactions/'+encodeURIComponent(b.dataset.emoji),{method:'DELETE'});await selectChannel(channel)});
  l.append(row)
 })
}
function showPicker(row,m){
 uiLock=true; let p=document.createElement('div');p.dataset.testid='emoji-picker';['😀','👍','❤️','😂','🎉','🚀','😄','👏','🔥','✅'].forEach(e=>{let b=document.createElement('button');b.dataset.testid='emoji-option';b.textContent=e;b.onclick=async()=>{await api('/messages/'+m.id+'/reactions',{method:'POST',body:{emoji:e}});p.remove();uiLock=false;await selectChannel(channel)};p.append(b)});row.append(p)
}
async function react(m){try{await api('/messages/'+m.id+'/reactions',{method:'POST',body:{emoji:'😀'}});selectChannel(channel)}catch(e){}}
async function openThread(m){uiLock=false;let p=$('[data-testid=thread-panel]');p.hidden=false;p.dataset.parent=m.id;p.querySelector('header').firstChild.textContent='Thread: '+m.body+' ';let d=await api('/messages/'+m.id+'/replies');p.querySelector('.thread-messages').innerHTML=(d.replies||[]).map(x=>`<p><b>${x.author.username}</b> ${x.body}</p>`).join('')}
async function send(body,parent){if(!body.trim()){return}await api('/channels/'+channel.id+'/messages',{method:'POST',body:{body,parent_id:parent||undefined}});await selectChannel(channel)}
$('[data-testid=auth-toggle]').onclick=()=>{let f=$('[data-testid=auth-form');let signup=f.dataset.mode!=='signup';f.dataset.mode=signup?'signup':'login';$('.auth-title').textContent=signup?'Create your account':'Log in to Huddle';$('[data-testid=auth-submit]').textContent=signup?'Sign up':'Log in';$$('.signup-only').forEach(x=>x.hidden=!signup)}
$('[data-testid=auth-form]').onsubmit=async e=>{e.preventDefault();let f=e.currentTarget,o=Object.fromEntries(new FormData(f));try{let d=await api('/auth/'+(f.dataset.mode==='signup'?'register':'login'),{method:'POST',body:o});token=d.token;localStorage.setItem('huddle.token',token);me=d.user;showApp()}catch(x){err(f,x)}}
$('[data-testid=logout-btn]').onclick=()=>{token=null;localStorage.removeItem('huddle.token');showAuth()}
$('[data-testid=workspace-create-form]').onsubmit=async e=>{e.preventDefault();let o=Object.fromEntries(new FormData(e.currentTarget));try{let d=await api('/workspaces',{method:'POST',body:o});ws=d.workspace;$('[data-testid=empty-state-create-workspace]').hidden=true;showApp()}catch(x){err(e.currentTarget,x)}}
$('[data-testid=send-btn]').parentElement.onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=message-input');try{uiLock=false;await send(i.value);i.value=''}catch(x){err(e.currentTarget,x)}}
$('[data-testid=thread-send]').parentElement.onsubmit=async e=>{
 e.preventDefault();let i=$('[data-testid=thread-input'),p=$('[data-testid=thread-panel]'),parent=+p.dataset.parent
 try{await send(i.value,parent);i.value='';let d=await api('/messages/'+parent+'/replies');p.querySelector('.thread-messages').innerHTML=(d.replies||[]).map(x=>`<p><b>${x.author.username}</b> ${x.body}</p>`).join('')}catch(x){err(e.currentTarget,x)}
}
$('[data-testid=close-thread]').onclick=()=>{$('[data-testid=thread-panel]').hidden=true}
$('[data-testid=new-channel-btn]').onclick=()=>{$('#create-channel-modal').hidden=false}
$('[data-testid=create-channel-cancel]').onclick=()=>{$('#create-channel-modal').hidden=true}
$('[data-testid=create-channel-form]').onsubmit=async e=>{
 e.preventDefault();let f=e.currentTarget,o=Object.fromEntries(new FormData(f));o.is_private=f.is_private.checked
 let duplicate=$$('[data-testid=channel-entry]').some(x=>(x.dataset.channelName||'').toLowerCase()===String(o.name||'').toLowerCase())
 if(duplicate){err(f,new Error('A channel with that name already exists'));return}
 try{let d=await api('/workspaces/'+ws.slug+'/channels',{method:'POST',body:o});$('#create-channel-modal').hidden=true;await loadWorkspaces();if(d.channel)selectChannel(d.channel)}
 catch(x){err(f,x)}
}
(async()=>{if(token)try{me=(await api('/auth/me')).user;showApp()}catch(e){showAuth()}else showAuth()})(); setInterval(()=>{if(channel&&!uiLock&&!document.querySelector('[data-testid=emoji-picker]'))selectChannel(channel,true).catch(()=>{})},700);
