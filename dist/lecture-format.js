/* One lecture structure for the reading view, print and editable Word export. */
(function () {
  'use strict';
  const escape=text=>String(text).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const inline=text=>escape(text).replace(/&lt;(\/?(?:sub|sup|i|strong))&gt;/gi,'<$1>');
  function blocks(text) {
    return String(text||'').split(/\r?\n/).map(line=>line.trim()).filter(Boolean).map(line=>{
      const plain=line.replace(/<\/?(?:sub|sup|i|strong)>/gi,'');
      const heading=/^<strong>[^]*<\/strong>$/i.test(line)&&plain.length<65||/^[一二三四五六七八九十]+、.{1,40}$/.test(plain);
      const formula=!heading&&/[=≈≃≡∝⇌→≤≥]/.test(plain)&&!/[。！？]/.test(plain)&&plain.length<200&&(plain.match(/[\u4e00-\u9fff]/g)||[]).length<12;
      return {kind:heading?'heading':formula?'formula':'paragraph',html:inline(line),text:plain};
    });
  }
  function html(text){return blocks(text).map(block=>block.kind==='heading'
    ?`<h5 class="ai-lecture-heading">${block.html}</h5>`
    :`<p class="${block.kind==='formula'?'ai-lecture-formula':'ai-lecture-paragraph'}">${block.html}</p>`).join('');}
  window.ChemyLecture={blocks,html};
})();
