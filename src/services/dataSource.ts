import {scenarios,type KBEntry,type Scenario} from '../data/scenarios';
export interface AgentResult { scenario:Scenario; learned?:KBEntry; live?:boolean; sessionId?:string; report?:Record<string,unknown>; backendMessage?:string }
export interface InvestigationDataSource { startInvestigation(scenarioId:string):Promise<AgentResult>; injectEvidence(sessionId?:string):Promise<Record<string,unknown>|undefined>; approve(sessionId?:string,actionIndex?:number):Promise<Record<string,unknown>|undefined>; reject(sessionId?:string,actionIndex?:number):Promise<Record<string,unknown>|undefined>; getKnowledgeBase():KBEntry[] }
const KEY='incidentiq-kb-v1';
export class MockDataSource {
 private active='';
 async startInvestigation(scenarioId:string):Promise<AgentResult>{this.active=scenarioId;return {scenario:scenarios.find(s=>s.id===scenarioId)!,learned:this.getKnowledgeBase().find(x=>x.scenarioId===scenarioId)};}
 async injectEvidence():Promise<Record<string,unknown>|undefined>{return;}
 async approve():Promise<Record<string,unknown>|undefined>{return;}
 async reject():Promise<Record<string,unknown>|undefined>{return;}
 getKnowledgeBase():KBEntry[]{try{return JSON.parse(localStorage.getItem(KEY)||'[]') as KBEntry[]}catch{return []}}
 save(entry:KBEntry){const entries=this.getKnowledgeBase();if(!entries.some(x=>x.scenarioId===entry.scenarioId)){entries.push(entry);localStorage.setItem(KEY,JSON.stringify(entries));}}
 reset(){localStorage.removeItem(KEY)}
}
export class ConnectedDataSource extends MockDataSource implements InvestigationDataSource {
 private sessionId?:string;
 async startInvestigation(scenarioId:string):Promise<AgentResult>{
  if(['memory','pool','cache'].includes(scenarioId)){
   try{const response=await fetch('/api/investigate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenarioId})});const payload=await response.json();if(!response.ok)throw new Error(payload.error||`Agent API returned ${response.status}`);this.sessionId=payload.sessionId;return {scenario:payload.scenario as Scenario,learned:this.getKnowledgeBase().find(x=>x.scenarioId===scenarioId),live:true,sessionId:this.sessionId,report:payload.report as Record<string,unknown>};}
   catch(error){return {scenario:{...scenarios.find(s=>s.id===scenarioId)!,agentStatus:'backend_unavailable',agentMessage:error instanceof Error?error.message:'Unable to reach the local agent API'},learned:this.getKnowledgeBase().find(x=>x.scenarioId===scenarioId),live:false,backendMessage:error instanceof Error?error.message:'Unable to reach the local agent API'};}
  }
  const fallback=await super.startInvestigation(scenarioId);return {...fallback,live:false};
 }
 async injectEvidence(sessionId=this.sessionId){if(!sessionId)return;const response=await fetch(`/api/investigations/${sessionId}/inject`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const payload=await response.json();if(!response.ok)throw new Error(payload.error||`Evidence injection returned ${response.status}`);return payload as Record<string,unknown>}
 async approve(sessionId=this.sessionId,actionIndex=0){if(!sessionId)return;const response=await fetch(`/api/investigations/${sessionId}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actionIndex})});const payload=await response.json();if(!response.ok)throw new Error(payload.error||`Approval returned ${response.status}`);return payload as Record<string,unknown>}
 async reject(sessionId=this.sessionId,actionIndex=0){if(!sessionId)return;const response=await fetch(`/api/investigations/${sessionId}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actionIndex})});const payload=await response.json();if(!response.ok)throw new Error(payload.error||`Rejection returned ${response.status}`);return payload as Record<string,unknown>}
}
export const mockDataSource=new ConnectedDataSource();
