'use strict';
(()=>{
  const library=globalThis.CTLanguageLibrary;
  const names=Object.fromEntries(Object.entries(library).map(([code,item])=>[code,item.label]));
  function variants(voices){
    return Object.entries(library).flatMap(([language,item])=>{
      const genders=['male','female'];
      if(voices.some(voice=>voice.language===language&&voice.gender==='unspecified'))genders.push('unspecified');
      return genders.map(gender=>{
        const compatible=voices.some(voice=>voice.language===language&&voice.gender===gender&&voice.compatible!==false);
        return {value:language+':'+gender,language,gender,label:item.label+' — '+({male:'мужской',female:'женский',unspecified:'пол не указан'})[gender],
          available:item.stt&&compatible,reason:!item.stt?'нет распознавания':!compatible?'нет готового голоса':''};
      });
    }).filter(item=>item.available).sort((a,b)=>a.label.localeCompare(b.label,'ru'));
  }
  function restoreVariant(voices,language,gender,selected){
    const options=variants(voices).filter(item=>item.language===language&&item.available);
    const chosen=voices.find(voice=>voice.id===selected&&voice.language===language);
    const match=options.find(item=>item.gender===(gender&&gender!=='all'?gender:chosen?.gender));
    return match?.value||(options.length===1?options[0].value:'');
  }
  const languages=voices=>Object.entries(names).map(([code,name])=>({code,name,
    available:library[code].stt&&voices.some(voice=>voice.language===code && voice.compatible!==false)}));
  const pair=(voices,source,target)=>Boolean(source && target && source!==target &&
    [source,target].every(code=>languages(voices).some(item=>item.code===code && item.available)));
  function forDirection(voices,source,target,direction,gender='all'){
    if(!pair(voices,source,target))return [];
    return voices.filter(voice=>voice.language===(direction==='incoming'?source:target)&&(gender==='all'||(voice.gender||'unspecified')===gender));
  }
  function ready(voices,installed,source,target,genders={}){
    return pair(voices,source,target) && ['incoming','outgoing'].every(direction=>
      forDirection(voices,source,target,direction,genders[direction]||'all').some(voice=>voice.compatible!==false &&
        voice.id===installed.selected?.[direction] && installed.voices?.some(item=>item.id===voice.id && item.version===voice.version)));
  }
  globalThis.CTVoiceSetup={names,languages,pair,forDirection,ready,variants,restoreVariant};
  if(typeof module!=='undefined')module.exports=globalThis.CTVoiceSetup;
})();
