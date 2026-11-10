const $=s=>document.querySelector(s), all=s=>[...document.querySelectorAll(s)];
let token=localStorage.getItem("huddle.token")||"", me=null, workspace=null, channel=null, messages=[];
window.__huddle_token=token;
async function api(method,path,body){
  const o={method,headers:{}}; if(token)o.headers.Authorization="Bearer "+token;
  if(body!==undefined){o.headers["Content-Type"]="application/json";o.body=JSON.stringify(body)}
  const r=await fetch("/api"+path,o); let d={}; try{d=await r.json()}catch{}
  return {status:r.status,data:d}
}
function showAuth(v){
  $("#auth-modal").hidden=!v;$("#app").hidden=v;
  if(!v && !$("[data-testid=workspace-settings-btn]")){
    const h=$("[data-testid=workspace-header]")||$("#app").querySelector(".sidebar header");
    if(h){const b=document.createElement("button");b.type="button";b.dataset.testid="workspace-settings-btn";b.dataset.buttonRole="secondary";b.textContent="Settings";h.appendChild(b)}
  }
}
function authError(x){const a=$("[data-testid=auth-form] [role=alert]");if(a){a.textContent=x;a.hidden=false}}
function saveToken(t){token=t;localStorage.setItem("huddle.token",t);window.__huddle_token=t}
function renderChannels(){
  const list=$('[data-testid=channel-list]');list.innerHTML="";
  (workspace?.channels||[]).filter(c=>!c.is_archived).forEach(c=>{
    const li=document.createElement("li");li.dataset.testid="channel-entry";li.dataset.channelId=c.id;li.dataset.channelName=c.name;li.textContent="# "+c.name;
    li.onclick=()=>selectChannel(c.id);list.appendChild(li)
  })
}
async function loadWorkspace(){
  const r=await api("GET","/workspaces"); const ws=r.data.workspaces||[];
  if(!ws.length){workspace=null;$("[data-testid=workspace-header] .ws-name").textContent="Create a workspace";$("[data-testid=empty-state-create-workspace]").hidden=false;return}
  workspace=(await api("GET","/workspaces/"+ws[0].slug)).data; $("[data-testid=workspace-header] .ws-name").textContent=workspace.workspace.name;
  $("[data-testid=empty-state-create-workspace]").hidden=true;renderChannels();
  const first=workspace.channels?.[0];if(first)selectChannel(first.id)
}
function human(t){try{return new Date(t).toLocaleTimeString([],{hour:"numeric",minute:"2-digit"})}catch{return""}}
function renderMessage(m){
  const row=document.createElement("div");row.dataset.testid="message";row.dataset.messageId=m.id;
  row.innerHTML=`<span class="avatar">${(m.author?.display_name||"?")[0]}</span><span class="author">${m.author?.display_name||"User"}</span><time datetime="${m.created_at}">${human(m.created_at)}</time><div data-testid="message-body"></div>${m.edited_at?'<span class="edited">(edited)</span>':""}<span class="reply-count">${m.reply_count?m.reply_count+" repl"+(m.reply_count==1?"y":"ies"):""}</span><div class="toolbar"><button data-testid="open-thread-btn">Thread</button><button data-testid="reaction-button">😊</button><button data-action="edit">Edit</button><button data-action="delete">Delete</button></div><div class="reactions"></div>`;
  row.querySelector("[data-testid=message-body]").textContent=m.body;
  row.querySelector("[data-testid=open-thread-btn]").onclick=()=>openThread(m.id);
  row.querySelector("[data-testid=reaction-button]").onclick=()=>picker(row,m);
  row.querySelector("[data-action=edit]").onclick=()=>editMessage(row,m);
  row.querySelector("[data-action=delete]").onclick=async()=>{await api("DELETE","/messages/"+m.id);row.remove();messages=messages.filter(x=>x.id!==m.id)}
  const rr=row.querySelector(".reactions");(m.reactions||[]).forEach(x=>{const b=document.createElement("button");b.dataset.testid="reaction-chip";b.textContent=x.emoji+" "+x.count;b.onclick=async()=>{if(x.user_ids.includes(me.id))await api("DELETE",`/messages/${m.id}/reactions/${encodeURIComponent(x.emoji)}`);else await api("POST","/messages/"+m.id+"/reactions",{emoji:x.emoji});await selectChannel(channel.id)};rr.appendChild(b)});
  return row
}
function renderMessages(){const l=$("[data-testid=message-list]");l.innerHTML="";if(!messages.length){l.textContent="No messages yet. Say hi!";return}messages.slice().reverse().forEach(m=>l.appendChild(renderMessage(m)))}
async function selectChannel(id){
  channel=(workspace.channels||[]).find(c=>c.id==id);if(!channel)return;
  $("[data-testid=channel-title]").textContent="#"+channel.name;$("[data-testid=channel-topic]").textContent=channel.topic||"";
  const r=await api("GET",`/channels/${id}/messages`);messages=r.data.messages||[];renderMessages()
}
async function openThread(id){
  $("[data-testid=thread-panel]").hidden=false;$("[data-testid=thread-panel]").dataset.parentId=id;
  const p=messages.find(x=>x.id==id);$("[data-testid=thread-panel]").querySelector(".thread-parent")?.remove();
  const h=document.createElement("div");h.className="thread-parent";h.textContent=p?.body||"";$("[data-testid=thread-panel]").prepend(h);
  const r=await api("GET",`/messages/${id}/replies`), box=$("[data-testid=thread-panel]"), area=box.querySelector(".thread-messages")||box;
  area.innerHTML="";
  (r.data.replies||[]).forEach(x=>{const d=document.createElement("div");d.className="thread-reply";d.textContent=x.body;area.appendChild(d)})
}
function picker(row,m){let p=row.querySelector("[data-testid=emoji-picker]");if(p)return;p=document.createElement("div");p.dataset.testid="emoji-picker";["😀","👍","❤️","😂","🎉","🚀","😄","👏"].forEach(e=>{const b=document.createElement("button");b.dataset.testid="emoji-option";b.textContent=e;b.onclick=async()=>{await api("POST",`/messages/${m.id}/reactions`,{emoji:e});await selectChannel(channel.id)};p.appendChild(b)});row.appendChild(p)}
function editMessage(row,m){const b=row.querySelector("[data-testid=message-body]"),i=document.createElement("input");i.name="edit-body";i.value=m.body;b.replaceWith(i);i.focus();i.onkeydown=async e=>{if(e.key==="Escape")renderMessages();if(e.key==="Enter"){await api("PATCH","/messages/"+m.id,{body:i.value});await selectChannel(channel.id)}}}
async function boot(){
  const q=new URLSearchParams(location.search);if(q.get("token")){saveToken(q.get("token"))}
  if(!token){showAuth(true);return}
  const r=await api("GET","/auth/me");if(r.status!==200){showAuth(true);return}
  me=r.data.user;$("[data-testid=current-user]").textContent=me.username||me.display_name||"";showAuth(false);await loadWorkspace()
}
document.addEventListener("DOMContentLoaded",()=>{
  const f=$('[data-testid=auth-form]');f.onsubmit=async e=>{e.preventDefault();const b=Object.fromEntries(new FormData(f));const r=await api("POST",f.dataset.mode==="signup"?"/auth/register":"/auth/login",b);if(r.status>=400){authError(r.data.error||"Authentication failed");return}saveToken(r.data.token);me=r.data.user;$("[data-testid=current-user]").textContent=me.username||me.display_name||"";showAuth(false);await loadWorkspace()};
  $('[data-testid=auth-toggle]').onclick=()=>{f.dataset.mode=f.dataset.mode==="signup"?"login":"signup";const d=f.querySelector('[name=display_name]');if(d)d.hidden=f.dataset.mode!=="signup"};
  $('[data-testid=logout-btn]').onclick=()=>{localStorage.removeItem("huddle.token");token="";showAuth(true)};
  const sendMessage=async()=>{const i=$("[data-testid=message-input]"),b=i.value.trim();if(!b||!channel)return;await api("POST",`/channels/${channel.id}/messages`,{body:b});i.value="";await selectChannel(channel.id)};
  $('[data-testid=send-btn]').onclick=e=>{e.preventDefault();sendMessage()};
  $("[data-testid=message-input]").onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();sendMessage()}};
  document.querySelector(".composer").onsubmit=e=>{e.preventDefault();sendMessage()};
  $('[data-testid=new-channel-btn]').onclick=()=>$("#create-channel-modal").hidden=false;
  $('[data-testid=create-channel-cancel]').onclick=()=>$("#create-channel-modal").hidden=true;
  $('[data-testid=create-channel-form]').onsubmit=async e=>{e.preventDefault();const b=Object.fromEntries(new FormData(e.target));b.is_private=$("[data-testid=create-channel-private]").checked;const r=await api("POST",`/workspaces/${workspace.workspace.slug}/channels`,b);if(r.status>=400){e.target.querySelector('[role=alert]').textContent=r.data.error;return}workspace.channels.push(r.data.channel);renderChannels();$("#create-channel-modal").hidden=true;selectChannel(r.data.channel.id)};
  $('[data-testid=close-thread]').onclick=()=>$("[data-testid=thread-panel]").hidden=true;
  const sendThread=async()=>{const i=$("[data-testid=thread-input]"),b=i.value.trim(),id=$("[data-testid=thread-panel]").dataset.parentId;if(!b||!id)return;await api("POST",`/channels/${channel.id}/messages`,{body:b,parent_id:+id});i.value="";await openThread(+id);await selectChannel(channel.id)};
  $('[data-testid=thread-send]').onclick=e=>{e.preventDefault();sendThread()};
  $('[data-testid=thread-panel] form').onsubmit=e=>{e.preventDefault();sendThread()};
  $("[data-testid=thread-input]").onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();sendThread()}};
  $('[data-testid=workspace-create-form]').onsubmit=async e=>{e.preventDefault();const b=Object.fromEntries(new FormData(e.target)),r=await api("POST","/workspaces",b);if(r.status===201)await loadWorkspace()};
  const wmodal=$("#workspace-settings-modal"), cm=$("#channel-settings-modal");
  async function renderMembers(){
    if(!workspace)return;
    const r=await api("GET",`/workspaces/${workspace.workspace.slug}/members`), pane=$("[data-testid=settings-pane-members]");
    pane.innerHTML="";
    (r.data.members||[]).forEach(m=>{
      const d=document.createElement("div");d.dataset.testid="member-row";d.dataset.userId=m.user_id;
      d.innerHTML=`<span>${m.user?.display_name||m.user_id}</span> <span data-testid="role-badge">${m.role}</span>`;
      if(m.user_id!==me.id){
        const sel=document.createElement("select");sel.dataset.testid="role-select";
        ["member","admin","guest"].forEach(x=>{const o=document.createElement("option");o.value=x;o.textContent=x;o.selected=x===m.role;sel.appendChild(o)});
        sel.onchange=async()=>{const z=await api("PATCH",`/workspaces/${workspace.workspace.slug}/members/${m.user_id}`,{role:sel.value});if(z.status<300)d.querySelector('[data-testid=role-badge]').textContent=sel.value};
        d.appendChild(sel)
      }
      pane.appendChild(d)
    })
  }
  function settingsTab(n){
    ["members","invitations","general"].forEach(x=>$(`[data-testid=settings-pane-${x}]`).hidden=x!==n);
    if(n==="members")renderMembers();
    if(n==="general"){$("[data-testid=workspace-name-input]").value=workspace.workspace.name;$("[data-testid=workspace-join-mode]").value=workspace.workspace.join_mode}
    if(n==="invitations")renderInvites()
  }
  async function renderInvites(){
    const l=$("[data-testid=invitations-list]");l.innerHTML="";
    const r=await api("GET",`/workspaces/${workspace.workspace.slug}/invitations`);
    (r.data.invitations||[]).forEach(x=>{const li=document.createElement("li");const c=document.createElement("span");c.dataset.testid="invitation-code";c.textContent=x.code;li.appendChild(c);l.appendChild(li)})
  }
  $('[data-testid=workspace-settings-btn]').onclick=()=>{wmodal.hidden=false;settingsTab("members")};
  $('[data-testid=workspace-settings-close]').onclick=()=>wmodal.hidden=true;
  $('[data-testid=settings-tab-members]').onclick=()=>settingsTab("members");
  $('[data-testid=settings-tab-invitations]').onclick=()=>settingsTab("invitations");
  $('[data-testid=settings-tab-general]').onclick=()=>settingsTab("general");
  $('[data-testid=create-invitation-btn]').onclick=()=>$("#create-invitation-form").hidden=false;
  $("#create-invitation-form").onsubmit=async e=>{e.preventDefault();const n=+e.target.max_uses.value||1,r=await api("POST",`/workspaces/${workspace.workspace.slug}/invitations`,{max_uses:n});if(r.status<300){e.target.hidden=true;await renderInvites()}};
  $(".general-form").onsubmit=async e=>{e.preventDefault();const n=$("[data-testid=workspace-name-input]").value,j=$("[data-testid=workspace-join-mode]").value,r=await api("PATCH",`/workspaces/${workspace.workspace.slug}`,{name:n,join_mode:j});if(r.status<300){workspace.workspace=r.data.workspace;$("[data-testid=workspace-header] .ws-name").textContent=n;$("[data-testid=workspace-header] .ws-name").textContent=n}};
  $('[data-testid=join-workspace-form]').onsubmit=async e=>{e.preventDefault();const code=e.target.code.value,r=await api("POST",`/invitations/${code}/accept`,{});const er=$("[data-testid=join-workspace-error]");if(r.status>=400){er.textContent=r.data.error||"Unable to join";er.hidden=false}else{er.hidden=true;await loadWorkspace()}};
  $('[data-testid=channel-settings-btn]').onclick=async()=>{if(!channel)return;cm.hidden=false;$("[data-testid=channel-settings-title]").textContent="#"+channel.name;await renderChannelMembers()};
  $('[data-testid=channel-settings-close]').onclick=()=>cm.hidden=true;
  async function renderChannelMembers(){const l=$("[data-testid=channel-members-list]");l.innerHTML="";const r=await api("GET",`/channels/${channel.id}/members`);(r.data.members||[]).forEach(m=>{const x=document.createElement("li");x.dataset.testid="channel-member-row";x.textContent=m.display_name||m.username;l.appendChild(x)})}
  $('[data-testid=channel-add-member-form]').onsubmit=async e=>{e.preventDefault();const name=e.target.username.value,r=await api("GET","/workspaces/"+workspace.workspace.slug+"/members");const m=(r.data.members||[]).find(x=>(x.user?.username||"")===name);if(m){await api("POST",`/channels/${channel.id}/members`,{user_id:m.user_id});await renderChannelMembers()}};
  $(".topic-form").onsubmit=async e=>{e.preventDefault();const t=$("[data-testid=channel-topic-input]").value,r=await api("PATCH",`/channels/${channel.id}`,{topic:t});if(r.status<300){channel=r.data.channel;$("[data-testid=channel-topic]").textContent=t}};
  $('[data-testid=archive-channel-btn]').onclick=async()=>{const r=await api("POST",`/channels/${channel.id}/archive`);if(r.status<300){$("[data-testid=archive-channel-btn]").hidden=true;$("[data-testid=unarchive-channel-btn]").hidden=false}};
  $('[data-testid=unarchive-channel-btn]').onclick=async()=>{const r=await api("POST",`/channels/${channel.id}/unarchive`);if(r.status<300){$("[data-testid=archive-channel-btn]").hidden=false;$("[data-testid=unarchive-channel-btn]").hidden=true}};
  boot();
  setInterval(async()=>{if(token&&channel){const r=await api("GET",`/channels/${channel.id}/messages`), next=r.data.messages||[];if(JSON.stringify(next.map(x=>[x.id,x.body,x.edited_at,x.reply_count]))!==JSON.stringify(messages.map(x=>[x.id,x.body,x.edited_at,x.reply_count]))) {messages=next;renderMessages()}}},800);
});
