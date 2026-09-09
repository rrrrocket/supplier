document.addEventListener("DOMContentLoaded",()=>{
  const root=document.querySelector("#supplier-directory");
  let page=1,pageSize=50;
  async function load(){
    const params=new URLSearchParams({page,page_size:pageSize});
    for(const[id,key]of[["directory-keyword","keyword"],["directory-category","category"],["directory-region","region"],["directory-type","supplier_type"],["directory-mode","cooperation_mode"]]){
      const value=document.querySelector(`#${id}`).value.trim();
      if(value)params.set(key,value);
    }
    root.innerHTML='<div class="table-empty">正在加载…</div>';
    try{
      const data=await Matrix.api(`/api/public/suppliers?${params}`);
      root.innerHTML=data.items.length?data.items.map(item=>`<article class="panel directory-card"><div class="panel-body"><span class="badge badge-approved">${Matrix.escapeHtml(item.supplier_type)}</span><h2>${Matrix.escapeHtml(item.supplier_name)}</h2><p>${Matrix.escapeHtml([item.province,item.city].filter(Boolean).join(" · ")||"地区待补充")}</p><div class="chip-row">${item.categories.map(v=>`<span class="chip">${Matrix.escapeHtml(v)}</span>`).join("")}</div><div class="info-list"><div class="info-row"><span>联系人</span><strong>${Matrix.escapeHtml(item.contact_name||"—")}</strong></div><div class="info-row"><span>电话</span><strong>${Matrix.escapeHtml(item.contact_phone||"—")}</strong></div><div class="info-row"><span>邮箱</span><strong>${Matrix.escapeHtml(item.contact_email||"—")}</strong></div></div><a class="btn btn-secondary" href="/operator#suppliers">登录后申请合作</a></div></article>`).join(""):'<div class="table-empty">没有符合条件的供应商</div>';
      MatrixPagination.render(document.querySelector("#directory-pagination"),{page,pageSize,total:data.total,onChange(next,nextSize){page=next;pageSize=nextSize;load();}});
    }catch(error){root.innerHTML=`<div class="table-empty">${Matrix.escapeHtml(error.message)}</div>`;}
  }
  document.querySelector("#directory-search").onclick=()=>{page=1;load();};
  load();
});
