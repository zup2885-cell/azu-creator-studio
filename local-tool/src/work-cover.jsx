import React,{useState} from 'react';
import {ImageOff} from 'lucide-react';
export function WorkCover({row,small=false}){
  const [failed,setFailed]=useState(false);
  return <div className={'work-cover '+(small?'work-cover-small':'')}>
    {row.cover&&!failed?<img src={row.cover} alt={row.title.split('#')[0].trim()+' 封面'} loading="lazy" onError={()=>setFailed(true)}/>:<span className="cover-unavailable"><ImageOff size={small?18:25}/>{!small&&<small>封面尚未取得</small>}</span>}
  </div>
}
