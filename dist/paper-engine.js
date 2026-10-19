/* Shared, deterministic selection rules; no generated questions or keyword fallback. */
(function(root) {
  'use strict';
  const normalize = s => String(s || '').normalize('NFKC').toLowerCase().replace(/[\s·・_—–-]+/g,'').trim();
  function distance(a,b) {
    let row = Array.from({length:b.length+1},(_,i)=>i);
    for (let i=1;i<=a.length;i++) {
      const next=[i];
      for (let j=1;j<=b.length;j++) next[j]=Math.min(next[j-1]+1,row[j]+1,row[j-1]+(a[i-1]===b[j-1]?0:1));
      row=next;
    }
    return row[b.length];
  }
  function resolve(query, concepts) {
    const key=normalize(query);
    if (!key) return {kind:'empty',concepts:[]};
    const names=c=>[c.name,...(c.aliases || [])].map(normalize);
    const exact=concepts.filter(c=>names(c).includes(key));
    if(exact.length) return {kind:exact.length===1?'exact':'ambiguous',concepts:exact};
    const related=concepts.filter(c=>names(c).some(n=>n.includes(key) || (key.length>=3 && n.length>=3 && distance(n,key)<=1)));
    return {kind:related.length?'suggestions':'unknown',concepts:related.slice(0,12)};
  }
  function matches(q,filters) {
    if(filters.topic && filters.topic!=='all' && q.topic!==filters.topic)return false;
    if(filters.edition && filters.edition!=='all' && String(q.edition??39)!==String(filters.edition))return false;
    const paper=(q.edition??39)===39?String(q.paper):`${q.edition??39}-${q.paper}`;
    return !filters.paper || filters.paper==='all' || paper===filters.paper;
  }
  const usable=link=>link.confidence>=.8 && [1,2,3].includes(link.strength) && link.subquestions?.length && link.reason?.trim();
  function availableConcepts(index,bank,filters={}) {
    const byId=new Map(bank.map(q=>[q.id,q])),counts=new Map(),seen=new Set();
    for(const entry of index.entries || []) {
      const q=byId.get(entry.id);
      if(!q || seen.has(q.id) || !matches(q,filters))continue;
      seen.add(q.id);
      for(const id of new Set((entry.links || []).filter(usable).map(link=>link.conceptId)))counts.set(id,(counts.get(id)||0)+1);
    }
    return (index.concepts || []).filter(c=>counts.has(c.id)).map(c=>({...c,count:counts.get(c.id)}))
      .sort((a,b)=>b.count-a.count || a.name.localeCompare(b.name,'zh-CN'));
  }
  function candidates(conceptId,index,bank,filters={}) {
    const byId=new Map(bank.map(q=>[q.id,q]));
    const result=[];
    for(const entry of index.entries || []) {
      const q=byId.get(entry.id);
      if(!q || !matches(q,filters)) continue;
      const links=(entry.links || []).filter(l=>l.conceptId===conceptId && usable(l));
      if(links.length) result.push({id:q.id,links,strength:Math.max(...links.map(l=>l.strength))});
    }
    return [...new Map(result.map(r=>[r.id,r])).values()];
  }
  function choose(pool,count,excluded=[],rng=Math.random) {
    if(!Number.isInteger(count)||count<1||count>50) throw new Error('题量须为 1～50 的整数。');
    const skip=new Set(excluded);
    return pool.filter(q=>!skip.has(q.id)).map(q=>({q,tie:rng()})).sort((a,b)=>b.q.strength-a.q.strength || a.tie-b.tie).slice(0,count).map(r=>r.q);
  }
  const api={normalize,resolve,candidates,choose,availableConcepts};
  if(typeof module!=='undefined' && module.exports) module.exports=api;
  else root.ChemyPaper=api;
})(typeof globalThis!=='undefined'?globalThis:this);
