import {scenarios,type KBEntry,type Scenario} from '../data/scenarios';
export interface InvestigationDataSource { startInvestigation(scenarioId:string):Promise<{scenario:Scenario;learned?:KBEntry}>; injectEvidence():Promise<void>; approve():Promise<void>; reject():Promise<void>; getKnowledgeBase():KBEntry[] }
const KEY='incidentiq-kb-v1';
export class MockDataSource implements InvestigationDataSource {
 private active='';
 async startInvestigation(scenarioId:string){this.active=scenarioId;return {scenario:scenarios.find(s=>s.id===scenarioId)!,learned:this.getKnowledgeBase().find(x=>x.scenarioId===scenarioId)};}
 async injectEvidence(){return;}
 async approve(){return;}
 async reject(){return;}
 getKnowledgeBase():KBEntry[]{try{return JSON.parse(localStorage.getItem(KEY)||'[]') as KBEntry[]}catch{return []}}
 save(entry:KBEntry){const entries=this.getKnowledgeBase();if(!entries.some(x=>x.scenarioId===entry.scenarioId)){entries.push(entry);localStorage.setItem(KEY,JSON.stringify(entries));}}
 reset(){localStorage.removeItem(KEY)}
}
export const mockDataSource=new MockDataSource();
