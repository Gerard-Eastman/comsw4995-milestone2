const $=s=>document.querySelector(s),all=s=>[...document.querySelectorAll(s)];
let token=localStorage.getItem('huddle.token')||new URLSearchParams(location.search).get('token')||'',me=null,channels=[],current=null,workspace=null;
if(token){localStorage.setItem('huddle.token',token);window.__huddle_token=token}
async function api(method,path,body){let o={method,headers:{...(token?{Authorization:'Bearer '+token}:{}),...(body?{'Content-Type':'application/json'}:{})}};if(body)o.body=JSON.stringify(body);let r=await fetch(path,o);let d={};try{d=await r.json()}catch{}return{status:r.status,data:d}}
function auth(show){$('#auth-modal').hidden=!show;$('#app').hidden=show}
function alertIn(f,t){let x=f.querySelector('[role=alert]');if(x)x.textContent=t||''}
function syncMode(){let f=$('[data-testid=auth-form]'),up=f.dataset.mode==='signup';f.querySelector('.auth-title').textContent=up?'Create your Huddle account':'Log in to Huddle';f.querySelector('[data-testid=auth-submit]').textContent=up?'Sign up':'Log in';f.querySelector('.signup-only').hidden=!up}
async function boot(){let f=$('[data-testid=auth-form]');f.dataset.mode='login';syncMode();if(!token){auth(true);return}let r=await api('GET','/api/auth/me');if(r.status!==200){token='';auth(true);return}me=r.data.user;auth(false);await load()}
async function load(){let r=await api('GET','/api/workspaces');let list=r.data.workspaces||[];if(!list.length){$('[data-testid=current-user]').textContent=me.username;$('[data-testid=empty-state-create-workspace]').hidden=false;return}workspace=list[0];$('.ws-name').textContent=workspace.name;$('[data-testid=current-user]').textContent=me.username;let d=await api('GET','/api/workspaces/'+workspace.slug);channels=d.data.channels||[];renderChannels();if(channels.length)selectChannel(channels[0].id)}
function renderChannels(){let l=$('[data-testid=channel-list]');l.innerHTML='';channels.forEach(c=>{let x=document.createElement('li');x.dataset.testid='channel-entry';x.dataset.channelId=c.id;x.dataset.channelName=c.name;x.textContent='# '+c.name;x.onclick=()=>selectChannel(c.id);l.append(x)})}
async function selectChannel(id){current=id;let c=channels.find(x=>x.id==id);if(!c)return;$('[data-testid=channel-title]').textContent='#'+c.name;$('[data-testid=channel-topic]').textContent=c.topic||'';let r=await api('GET','/api/channels/'+id+'/messages'),l=$('[data-testid=message-list]');l.innerHTML='';let ms=(r.data.messages||[]).reverse();if(!ms.length){l.textContent='No messages yet. Say hi!';return}ms.forEach(renderMessage)}
function renderMessage(m){
 let x=document.createElement('div');x.dataset.testid='message';x.dataset.messageId=m.id;
 x.innerHTML='<span class="avatar">'+(m.author.display_name||m.author.username)[0]+'</span><span class="author">'+(m.author.display_name||m.author.username)+'</span><time datetime="'+m.created_at+'">'+new Date(m.created_at).toLocaleTimeString()+'</time><div data-testid="message-body"></div><span class="reply-count"></span><span class="reactions"></span><button data-testid="open-thread-btn">Thread</button><button data-testid="reaction-button">😀</button><button data-action="edit">Edit</button><button data-action="delete">Delete</button>';
 x.querySelector('[data-testid=message-body]').textContent=m.body;
 if(m.edited_at){let e=document.createElement('span');e.className='edited';e.textContent=' (edited)';x.append(e)}
 let rc=x.querySelector('.reply-count');if(m.reply_count)rc.textContent=m.reply_count+' '+(m.reply_count===1?'reply':'replies');
 (m.reactions||[]).forEach(r=>{let b=document.createElement('button');b.dataset.testid='reaction-chip';b.textContent=r.emoji+' '+r.count;b.onclick=async()=>{if(r.user_ids.includes(me.id))await api('DELETE','/api/messages/'+m.id+'/reactions/'+encodeURIComponent(r.emoji));else await api('POST','/api/messages/'+m.id+'/reactions',{emoji:r.emoji});selectChannel(current)};x.querySelector('.reactions').append(b)});
 x.querySelector('[data-action=delete]').onclick=async()=>{await api('DELETE','/api/messages/'+m.id);x.remove()};
 x.querySelector('[data-action=edit]').onclick=()=>{let i=document.createElement('input');i.name='edit-body';i.value=m.body;x.querySelector('[data-testid=message-body]').replaceWith(i);i.focus();i.onkeydown=async e=>{if(e.key==='Escape')selectChannel(current);if(e.key==='Enter'){await api('PATCH','/api/messages/'+m.id,{body:i.value});selectChannel(current)}}};
 x.querySelector('[data-testid=open-thread-btn]').onclick=()=>openThread(m.id);
 x.querySelector('[data-testid=reaction-button]').onclick=()=>{
  let old=x.querySelector('[data-testid=emoji-picker]');if(old){old.hidden=!old.hidden;return}
  let pick=document.createElement('div');pick.dataset.testid='emoji-picker';['👍','❤️','😀','😂','🎉','🚀','😎','👏'].forEach(e=>{let b=document.createElement('button');b.dataset.testid='emoji-option';b.textContent=e;b.onclick=async()=>{await api('POST','/api/messages/'+m.id+'/reactions',{emoji:e});pick.hidden=true;selectChannel(current)};pick.append(b)});x.append(pick)
 };
 $('[data-testid=message-list]').append(x)
}
async function openThread(id){
 let p=await api('GET','/api/messages/'+id+'/replies'),parent=await api('GET','/api/channels/'+current+'/messages');
 let pm=(parent.data.messages||[]).find(x=>x.id==id),panel=$('[data-testid=thread-panel]');
 panel.hidden=false;panel.dataset.parent=id;let box=panel.querySelector('.thread-messages');box.innerHTML='';
 if(pm){let d=document.createElement('div');d.className='thread-parent';d.textContent=pm.body;box.append(d)}
 (p.data.replies||[]).forEach(renderThread)
}
function renderThread(m){let d=document.createElement('div');d.textContent=(m.author.display_name||m.author.username)+': '+m.body;$('[data-testid=thread-panel] .thread-messages').append(d)}
$('[data-testid=thread-send]').closest('form').onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=thread-input]'),id=$('[data-testid=thread-panel]').dataset.parent;if(!i.value.trim())return;await api('POST','/api/channels/'+current+'/messages',{body:i.value,parent_id:Number(id)});i.value='';openThread(Number(id));selectChannel(current)}
$('[data-testid=auth-toggle]').onclick=()=>{let f=$('[data-testid=auth-form]');f.dataset.mode=f.dataset.mode==='login'?'signup':'login';syncMode()}
$('[data-testid=auth-form]').onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(e.target)),up=e.target.dataset.mode==='signup',r=await api('POST',up?'/api/auth/register':'/api/auth/login',d);if(r.status>=400){alertIn(e.target,r.data.error);return}token=r.data.token;localStorage.setItem('huddle.token',token);window.__huddle_token=token;me=r.data.user;$('[data-testid=current-user]').textContent=me.username;alertIn(e.target,'');auth(false);load()}
$('[data-testid=workspace-create-form]').onsubmit=async e=>{e.preventDefault();let r=await api('POST','/api/workspaces',Object.fromEntries(new FormData(e.target)));if(r.status>=400){alertIn(e.target,r.data.error);return}workspace=r.data.workspace;$('[data-testid=empty-state-create-workspace]').hidden=true;await load()}
$('[data-testid=new-channel-btn]').onclick=()=>$('#create-channel-modal').hidden=false
$('[data-testid=create-channel-cancel]').onclick=()=>$('#create-channel-modal').hidden=true
$('[data-testid=create-channel-form]').onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(e.target));d.is_private=e.target.is_private.checked;let r=await api('POST','/api/workspaces/'+workspace.slug+'/channels',d);if(r.status>=400){alertIn(e.target,r.data.error);return}channels.push(r.data.channel);renderChannels();$('#create-channel-modal').hidden=true;selectChannel(r.data.channel.id)}
$('[data-testid=send-btn]').closest('form').onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=message-input]');if(!i.value.trim())return;await api('POST','/api/channels/'+current+'/messages',{body:i.value});i.value='';selectChannel(current)}
$('[data-testid=close-thread]').onclick=()=> $('[data-testid=thread-panel]').hidden=true
$('[data-testid=logout-btn]').onclick=()=>{localStorage.removeItem('huddle.token');token='';auth(true)}
boot()

setInterval(()=>{if(token&&current)selectChannel(current)},1000);
