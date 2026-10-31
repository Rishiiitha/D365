import {useEffect,useMemo,useState} from 'react';
import {Activity,ArrowUpRight,Command,Contrast,Database,Ellipsis,Layers,Menu,Radio,RotateCcw,ShieldCheck,Sun,Workflow,Zap} from 'lucide-react';
import {scenarios} from './data/scenarios';
import {useInvestigation} from './hooks/useInvestigation';
import {AnomalyList,ApprovalBar,ConfidenceChart,DependencyGraph,EvidenceDrawer,HypothesisCards,ImpactPanel,KBPanel,PlanChecklist,RemediationList,ReplanPanel,Status,Stopwatch,TimelineCard,ToolFeed,VerificationChart} from './components/Sections';
import type {Evidence} from './data/scenarios';

type View='overview'|'hypothesis'|'impact'|'recovery';
export default function App(){
 const [scenarioId,setScenarioId]=useState('memory');
 const [theme,setTheme]=useState<'dark'|'light'>('dark');
 const [view,setView]=useState<View>('overview');
 const [drawerId,setDrawerId]=useState<string>();
 const [menu,setMenu]=useState(false);
 const [mobileNav,setMobileNav]=useState(false);
 const selectedScenario=scenarios.find(x=>x.id===scenarioId)!;
 const state=useInvestigation(selectedScenario);
 const [backendMeta,setBackendMeta]=useState<Record<string,{title:string;service:string}>>({});
 const scenario=state.activeScenario??(backendMeta[scenarioId]?{...selectedScenario,title:backendMeta[scenarioId].title,service:backendMeta[scenarioId].service}:selectedScenario);
 useEffect(()=>{fetch('/api/scenarios').then(r=>r.ok?r.json():null).then(data=>{if(data?.scenarios)setBackendMeta(Object.fromEntries(data.scenarios.map((x:{id:string;title:string;service:string})=>[x.id,{title:x.title,service:x.service}])))}).catch(()=>{});},[]);
 const evidence=useMemo(()=>scenario.evidence.find(e=>e.id===drawerId),[scenario,drawerId]);
 const stage=state.phase==='idle'?0:state.revealed;
 const show=(n:number)=>stage>=n||['awaiting_approval','replanning','awaiting_revised_approval','rejected','executing','verifying','resolved','learned'].includes(state.phase);
 const reset=()=>{state.reset();setMenu(false);setView('overview')};
 const tabs:[View,string][]=[['overview','Overview'],['hypothesis','Hypothesis'],['impact','Impact assessment'],['recovery','Recovery']];
 const defaultSources:[string,string][]=[['Application logs','128 records'],['Service metrics','36 series'],['Deploy history','7 changes'],['Distributed traces','24 spans'],['Support tickets','41 linked']];
 const sourceRows=scenario.dataMode==='live'&&scenario.sourceAvailability?Object.entries(scenario.sourceAvailability).filter(([name,info])=>!['key_evidence','verification_metrics'].includes(name)&&info.status!=='missing'&&info.status!=='excluded').map(([name,info])=>[name.replace(/_/g,' '),info.record_count===undefined?info.status:`${info.record_count.toLocaleString()} records`] as [string,string]):defaultSources;
 return <div className={`app-shell ${theme}`}>
  <aside className={`sidebar ${mobileNav?'mobile-open':''}`}>
   <div className="brand"><div className="brand-symbol"><Activity size={19}/></div><div><b>Incident<span>IQ</span></b><small>INCIDENT COMMAND</small></div><button aria-label="Close navigation" className="icon-button mobile-close" onClick={()=>setMobileNav(false)}>×</button></div>
   <div className="workspace-label"><span>WORKSPACE</span><span className="workspace-dot"/>PRODUCTION</div>
   <div className="nav-caption">ACTIVE SCENARIOS <span>05</span></div>
   <nav className="scenario-nav" aria-label="Failure scenarios">{scenarios.map((s,i)=><button key={s.id} className={`scenario-tab ${scenarioId===s.id?'active':''}`} onClick={()=>{setScenarioId(s.id);setMobileNav(false)}}><span className="scenario-index">0{i+1}</span><span className="scenario-name"><b>{backendMeta[s.id]?.title??s.title}</b><small>{backendMeta[s.id]?.service??s.service}</small></span><span className="severity-dot sev2"/></button>)}</nav>
   <div className="sidebar-spacer"/><div className="kb-counter"><div className="kb-icon"><Database size={16}/></div><div><b>Knowledge base</b><small>Learned resolutions</small></div><strong>{state.kb.length.toString().padStart(2,'0')}</strong></div>
   <div className="sidebar-footer"><span className="online-dot"/> All systems operational <span className="version">v0.9.4</span></div>
  </aside>
  <main className="main">
   <header className="topbar"><div className="crumb"><button className="icon-button nav-open" aria-label="Open navigation" onClick={()=>setMobileNav(true)}><Menu size={17}/></button><span>INCIDENTS</span><span className="crumb-slash">/</span><b>{scenario.incidentId}</b></div><div className="top-actions"><span className="environment"><span className="online-dot"/> PROD · US-EAST-1</span><button className="icon-button theme-toggle" aria-label="Toggle color theme" title="Toggle theme" onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?<Sun size={16}/>:<Contrast size={16}/>}</button><div className="menu-wrap"><button className="icon-button" aria-label="Open demo menu" onClick={()=>setMenu(!menu)}><Ellipsis size={19}/></button>{menu&&<div className="dropdown"><button onClick={reset}><RotateCcw size={14}/> Reset demo</button><div className="dropdown-hint">Clears learned incidents and run state</div></div>}</div><div className="avatar">OP</div></div></header>
   <div className="content">
    <div className="page-heading"><div><div className="eyebrow heading-eyebrow"><span className="workspace-dot"/> INCIDENT INVESTIGATION <span className="eyebrow-sep">/</span> {scenario.severity}</div><div className="title-row"><h1>{scenario.title}</h1><Status phase={state.phase}/></div><div className="heading-sub"><span><Layers size={14}/>{scenario.service}</span><span className="sub-sep">·</span><span>{scenario.incidentId}</span><span className="sub-sep">·</span><span>{scenario.dataMode==='live'?'Real dataset · UTC timestamps':backendMeta[scenarioId]?'Real dataset ready · click start to analyse locally':'Demo-only scenario · no workspace data folder'}</span></div></div><div className="heading-actions"><div className="metric-pill"><span className="metric-label">INVESTIGATION TIME</span><Stopwatch seconds={state.elapsed}/></div><div className="metric-pill sources-pill"><span className="metric-label">SOURCES CONSULTED</span><b>{scenario.dataMode==='live'?scenario.sourceCount:state.phase==='idle'?'0':Math.min(10,Math.max(1,state.revealed))}<span> / {scenario.dataMode==='live'?scenario.sourceTotal:10}</span></b></div><button className="button primary start-button" onClick={state.start}><Zap size={15}/>{['learned','resolved'].includes(state.phase)?'Re-run investigation':state.phase==='idle'?'Start investigation':'Restart run'}</button></div></div>
    <nav className="view-tabs" aria-label="Incident views" role="tablist">{tabs.map(([key,label])=><button key={key} role="tab" aria-selected={view===key} className={`view-tab ${view===key?'active':''}`} onClick={()=>setView(key)}>{label}{key==='hypothesis'&&<span>2</span>}</button>)}</nav>
    {state.liveError&&<div className="data-source-banner warning"><Radio size={16}/><div><b>Agent action could not be completed</b><span>{state.liveError}</span></div></div>}
    {state.fast&&<div className="matched-banner"><div className="matched-icon"><Database size={16}/></div><div><b>Matched past incident {state.learned?.id} <span>(94% similarity)</span></b><small>Known cause confirmed from your incident history. Ruled-out hypotheses skipped.</small></div><span className="time-saved"><Zap size={12}/>Time saved: {Math.max(0,(state.learned?.resolutionTime||0)-state.elapsed)}s</span></div>}
    {state.phase==='learned'&&state.learned&&<div className="resolved-banner"><ShieldCheck size={18}/><div><b>Incident resolved</b><span>Recovery verified · Investigation {state.elapsed}s · Resolution {state.learned.resolutionTime}s</span></div><span className="resolved-check">RECOVERED</span></div>}
    <div className="dashboard-grid"><div className="primary-column">
     {view==='overview'&&<><TimelineCard scenario={scenario} onOpen={setDrawerId}/><DependencyGraph scenario={scenario}/><AnomalyList scenario={scenario}/></>}
     {view==='hypothesis'&&<>{scenario.dataMode==='live'&&!scenario.hypotheses.length?<section className="agent-empty"><div className="eyebrow">LIVE AGENT RESULT</div><h2>No agent hypotheses were returned</h2><p>{scenario.agentMessage||'The deterministic data pipeline completed, but this run did not produce model-generated hypotheses.'}</p></section>:<><HypothesisCards scenario={scenario} onOpen={setDrawerId} confidenceBoost={state.injected}/><ConfidenceChart scenario={scenario}/></>}</>}
     {view==='impact'&&<ImpactPanel scenario={scenario} phase={state.phase}/>}
     {view==='recovery'&&<>
      {show(5)&&(!scenario.dataMode||scenario.plan.length>0)&&<PlanChecklist scenario={scenario} replanning={state.injected}/>}
      {show(6)&&(!scenario.dataMode||scenario.toolCalls.length>0)&&<ToolFeed scenario={scenario} onOpen={setDrawerId}/>}
      {show(9)&&scenario.remediations.length>0&&<RemediationList scenario={scenario} replanning={state.injected} rejected={state.rejected} rejectedIndex={state.rejectedIndex} selectedRemediation={state.selectedRemediation} phase={state.phase} onApprove={state.approve} onReject={state.reject}/>}
      {show(10)&&(!scenario.dataMode||scenario.remediations.length>0)&&<ApprovalBar phase={state.phase} onInject={state.inject} allowInject/>}
      {state.phase==='rejected'&&<div className="guidance-note"><span>OPTION REJECTED</span><b>Choose another recovery option</b><p>The rejected option is removed from the list. Approve or reject any remaining option above.</p></div>}
      <ReplanPanel scenario={scenario} visible={state.injected} onOpen={setDrawerId}/>
      <VerificationChart phase={state.phase} scenario={scenario} verification={state.liveVerification}/>
      {state.phase==='executing'&&<div className="execution-card"><div className="execution-head"><span><Activity size={15}/> Executing approved recovery</span><span>SIMULATED</span></div><div className="execution-track"><i/></div><small>{scenario.remediations[state.selectedRemediation]?.title}</small></div>}
      <KBPanel entry={state.phase==='learned'?state.learned:undefined}/>
      {view==='recovery'&&state.phase==='idle'&&<div className="empty-state"><Workflow size={18}/><span>Start an investigation to review the plan, tool activity, and recovery options.</span></div>}
      {view==='recovery'&&scenario.dataMode==='live'&&state.phase==='agent_unavailable'&&<div className="agent-empty"><div className="eyebrow">LIVE AGENT STATUS</div><h2>Analysis stopped before hypothesis generation</h2><p>{scenario.agentMessage}</p><small>Real logs, metrics, traces, impact, and service edges above come from the selected data folder. No placeholder cause or recovery has been inserted.</small></div>}
     </>}
    </div>
    <aside className="side-column"><div className="side-sticky">
     <div className="side-card agent-card"><div className="agent-head"><div className="agent-avatar"><Workflow size={16}/></div><div><b>Investigation agent</b><small>Autonomous · read-only tools</small></div><Radio className="agent-radio" size={15}/></div><div className="agent-state"><span className={`agent-pulse ${state.phase==='idle'?'idle':''}`}/><span>{state.phase==='idle'?'Standing by':state.phase==='learned'?'Resolution learned':state.phase.replace(/_/g,' ')}</span></div><div className="agent-progress"><div style={{width:`${Math.min(100,stage*9)}%`}}/></div><div className="agent-foot"><span>Investigation stages</span><b>{Math.min(stage,11)} <span>/ 11</span></b></div></div>
     <div className="side-card sources-card"><div className="sources-head"><span>{scenario.dataMode==='live'?'LOADED DATA SOURCES':'CONNECTED SOURCES'}</span><span>{scenario.dataMode==='live'?'READ':'DEMO'}</span></div>{sourceRows.map(([a,b],i)=><div className="source-row" key={a}><span className={`source-status s${i}`}/><span>{a}</span><small>{b}</small></div>)}<button className="view-sources" onClick={()=>{setView('recovery');setTimeout(()=>document.getElementById('tool-activity')?.scrollIntoView({behavior:'smooth'}),0)}}>View tool activity <ArrowUpRight size={12}/></button></div>
     <div className="side-card past-card"><div className="past-head"><span>RELATED INCIDENTS</span><span className="subtle">1 match</span></div>{scenario.pastIncidents.map(x=><div className="past-item" key={x.id}><div><b>{x.id}</b><span>{x.title}</span></div><strong>{x.similarity}</strong><p>{x.note}</p></div>)}</div>
     <div className="side-footer"><span><Command size={11}/> IncidentIQ Ops</span><span>DEMO ENVIRONMENT</span></div>
    </div></aside></div>
    <footer className="page-footer"><span>IncidentIQ <span>·</span> Autonomous Incident Investigation</span><span>Demo environment <i className="online-dot"/></span></footer>
   </div>
  </main>
  <EvidenceDrawer evidence={evidence as Evidence|undefined} onClose={()=>setDrawerId(undefined)}/>
 </div>
}
