import {expect, test, type Page} from '@playwright/test'

const names = ['BUYLOW', 'BUYHIGH', 'SELLLOW', 'SELLHIGH', 'WAIT', 'MISSING']
const session = '2026-10-13'
type Fixture = {phase: string; paper: boolean; lost: boolean; expired: boolean; quoteMissing: boolean; liveReads: number; diagnostics: string[]; recordedMode?: 'original' | 'foreign' | 'bytes' | 'late' | 'paged'; recordedReads?: number; originalMode?: 'original' | 'foreign' | 'size'; originalReads?: number; originalDelay?: number; denseMarkers?: boolean; installedHistory?: boolean; numerical?: 'execute' | 'wait'; numericalForeign?: boolean; numericalExpired?: boolean; publicationV2?: boolean; noSellSignals?: boolean; simulationPolicy?: string; signalUntil?: string; allocationUntil?: string; allocationWrong?: boolean; allocationMissing?: boolean; regularFallback?: boolean; publishedPlan?: boolean; independentSizing?: boolean; independentSignalWrong?: boolean; targetWeight?: number; simulationIdentityWrong?: boolean; entryAt?: number; formingSignal?: boolean; chartFrames?: string[]; zoomHistory?: boolean; chartSessions?: number[]; currentSessionBars?: boolean}

type ReferenceFixture = Fixture & {referenceMode?: 'trim' | 'exit' | 'buy'; referenceUnknown?: boolean; referenceObserved?: boolean; referenceResolved?: boolean; referenceBookInvalid?: boolean; numericalQuoteUntil?: string; persistedPosition?: number; persistedInvalid?: 'unavailable' | 'foreign' | 'book'; assessmentMissing?: boolean}

// Supply explicit reference-mode API fixtures without changing any production data or clocks.
function referenceFixture(data: unknown, path: string, state: ReferenceFixture, at: string, now: number): unknown {
  if (!state.referenceMode) return data
  const value = data as Record<string, any>
  const action = state.referenceMode==='buy' ? 'Buy' : 'Sell'
  const size = state.referenceMode==='buy' ? .0005 : state.referenceMode==='exit' ? .2 : .13
  const position = state.persistedPosition ?? (state.referenceMode==='exit' ? 0 : .143)
  const basis = state.referenceObserved ? 'observed_hypothetical_reference_not_viewer_order' : 'standing_counterfactual_reference_transition_not_viewer_order'
  if (path.endsWith('/model-allocation')) {
    if (state.referenceUnknown) {
      value.grade_signals.MISSING={...value.grade_signals.MISSING,grade:null,action:'unavailable'}
      value.rows.MISSING.evidence={...value.rows.MISSING.evidence,grade:null}
    }
    if (state.referenceMode==='exit') {
      value.rows.BUYHIGH.target_weight=0
      value.rows.BUYHIGH.evidence={...value.rows.BUYHIGH.evidence,grade:'B',model_position_size:0}
      value.grade_signals.BUYHIGH={...value.grade_signals.BUYHIGH,grade:'B',action:'sell'}
    }
    const entry=value.entry_assessment
    entry.version=state.referenceObserved ? 'strategy-numerical-entries/3' : 'strategy-numerical-entries/2';entry.sizing_basis=basis
    entry.reference_progression=state.referenceObserved ? 'later_observed_hypothetical_quote_proxy' : 'standing_no_fills_assumed';entry.recommendation_not_fill=true
    if(state.referenceObserved) Object.assign(entry,{execution_basis:'later_observed_IEX_bid_ask_proxy_not_actual_fill',day_id:'b'.repeat(64),book_sha256:state.referenceBookInvalid ? 'invalid' : 'c'.repeat(64)})
    entry.rows=Object.fromEntries(Object.keys(value.rows).map(name=>[name,{state:'no_trade',action:null,size_weight:0,
      model_position_weight:value.rows[name].target_weight,reference_units:0,proposed_units:0,quote_at:null,valid_until:at,
      evidence:{...value.rows[name].evidence,trade_size:0,sizing_basis:basis,completed_candle_at:entry.completed_at}}]))
    entry.rows.BUYHIGH={state:state.numerical,action,size_weight:size,model_position_weight:position,
      reference_units:.003,proposed_units:state.referenceMode==='exit' ? .003 : .0013,quote_at:at,
      valid_until:state.numericalQuoteUntil ?? new Date(state.numericalExpired ? now-1000 : now+20000).toISOString(),
      evidence:{...value.rows.BUYHIGH.evidence,model_position_size:position,trade_size:size,sizing_basis:basis,
        completed_candle_at:entry.completed_at,timing_reason:'Original reference numerical timing',features:{ema_21_distance:-.0944}}}
    if(state.referenceObserved) for(const row of Object.values(entry.rows) as Record<string,any>[]) Object.assign(row,{attempt_resolved:false,objective_pending:row.action!==null})
    if(state.referenceResolved) Object.assign(entry.rows.BUYHIGH,{state:'no_trade',action:null,size_weight:0,proposed_units:0,attempt_resolved:true,objective_pending:true,
      evidence:{...entry.rows.BUYHIGH.evidence,trade_size:0}})
    if(state.persistedPosition!==undefined){
      const viewBasis='original_persisted_daily_reference_targets_not_viewer_holdings'
      value.reference_positions={version:'strategy-reference-positions/1',basis:viewBasis,status:state.persistedInvalid==='unavailable' ? 'unavailable' : 'available',
        snapshot_id:(state.persistedInvalid==='foreign' ? '0' : 'e').repeat(64),publication_receipt_sha256:value.receipt_sha256,
        strategy_identity:value.strategy_identity,session:value.session,valid_until:value.valid_until,
        day_id:'b'.repeat(64),book_sha256:(state.persistedInvalid==='book' ? '0' : 'c').repeat(64),generation:0,
        reader_sha256:'1'.repeat(64),receipt_sha256:'2'.repeat(64),rows:Object.fromEntries(Object.entries(value.rows).map(([name,row])=>{
          const original=row as Record<string,any>,weight=name==='BUYHIGH' ? position : original.target_weight
          return [name,{target_weight:weight,evidence:{...original.evidence,model_position_size:weight,sizing_basis:viewBasis}}]
        }))}
      if(state.assessmentMissing) value.entry_assessment={version:'strategy-numerical-entries/1',status:'unavailable',rows:{}}
    }
  } else if (path.endsWith('/recommendations') && path.includes('/strategy-simulation/')) {
    value.items=value.items.map((item: Record<string, unknown>)=>({...item,action,size_weight:size}))
  } else if (path.endsWith('/recommendation') && path.includes('/strategy-simulation/')) {
    value.original={...value.original,action,size_weight:size,entry_version:state.referenceObserved ? 'strategy-numerical-entries/3' : 'strategy-numerical-entries/2',
      model_position_weight:position,reference_units:.003,proposed_units:state.referenceMode==='exit' ? .003 : .0013,
      evidence:{...value.original.evidence,model_position_size:position,trade_size:size,sizing_basis:basis,
        ...(state.referenceObserved ? {reference_position_size:position+size,waiting_log_utility:-.001} : {})}}
  }
  return value
}

// A persisted model objective survives expired or absent candle advice in both the list and every chart frame.
test('Persisted position stays consistent after candle expiry and reload without a fresh-capital fallback',async ({page,baseURL})=>{
  const state=fixture() as ReferenceFixture
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceObserved:true,persistedPosition:.058,
    entryAt:Date.now()-900100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('5.8%')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 5.8%')
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Wait · Size —')
  }
  state.assessmentMissing=true
  await page.reload()
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('5.8%')
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  expect(state.diagnostics).toEqual([])
})

// An expired nightly publication is a calm last plan, not an integrity failure or a fresh recommendation.
test('Awaiting tonight plan keeps the last plan visible without an unavailable message',async ({page,baseURL})=>{
  const state=fixture()
  state.publicationV2=true
  await install(page,baseURL!,state)
  const expiredAt=new Date(Date.now()-60*60000).toISOString(), nextAt=new Date(Date.now()+60*60000).toISOString()
  await page.route('**/model-allocation',route=>route.fulfill({json:{
    version:'strategy-model-allocation/2',status:'awaiting_nightly',policy:'grade-led-learned-sizing/1',session:'2026-10-19',
    observed_at:'2026-10-19T23:49:42Z',as_of:expiredAt,published_at:expiredAt,valid_until:expiredAt,
    strategy_identity:'d'.repeat(64),snapshot_id:'e'.repeat(64),receipt_sha256:'f'.repeat(64),
    basis:'account_independent_unit_capital_targets',account_basis:'no_account_inputs',
    timing_basis:'nightly_position_size_not_immediate_trade_size',expired_at:expiredAt,next_publication_at:nextAt,last_session:'2026-10-19',
    last_rows:{
      BUYHIGH:{target_weight:.143,evidence:{inputs_as_of:'2026-10-19',grade:'A',model_position_size:.143}},
      BUYLOW:{target_weight:0,evidence:{inputs_as_of:'2026-10-19',grade:'A',model_position_size:0}},
      SELLHIGH:{target_weight:0,evidence:{inputs_as_of:'2026-10-19',grade:'C',model_position_size:0}},
    },
  }}))
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('Plan status')).toContainText("tonight's publishes at")
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  await expect(board.locator('tbody tr[data-ticker="BUYHIGH"]')).toHaveClass(/opacity-70/)
  await expect(board.getByText('last plan',{exact:true})).toHaveCount(3)
  await expect(board.getByLabel('Signal coverage')).toContainText('3 last-plan rows · awaiting tonight')
  await expect(board.getByLabel('Data as of')).toContainText('Plan 2026-10-19 (last plan)')
  await expect(board).not.toContainText('Strategy recommendations unavailable')
  expect(state.diagnostics).toEqual([])
})

// Reference read failures never expose the unrelated fresh-capital percentage or an executable trade.
test('Persisted position rejects unavailable foreign and mismatched-book evidence',async ({page,baseURL})=>{
  const state=fixture() as ReferenceFixture
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceObserved:true,persistedPosition:.058,
    persistedInvalid:'unavailable',entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('Unavailable')
  state.persistedInvalid='foreign';await page.reload()
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('Unavailable')
  state.persistedInvalid='book';await page.reload()
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('5.8%')
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  expect(state.diagnostics).toEqual([])
})

// Expire an executable trade on its real quote deadline while keeping the same persisted objective in list and chart.
test('Persisted position survives the original trade permission deadline',async ({page,baseURL})=>{
  const state=fixture() as ReferenceFixture
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceObserved:true,persistedPosition:.058,
    numericalQuoteUntil:new Date(Date.now()+5000).toISOString(),entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('13.0%')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('5.8%')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Sell · Size 13.0%')
  await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Wait · Size —',{timeout:10000})
  await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 5.8%')
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('13.0%')
  await expect(board.getByLabel('BUYHIGH verdict cell',{exact:true})).toContainText('refreshing')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('5.8%')
  expect(state.diagnostics).toEqual([])
})

// Exercise live signal evidence with deliberately contrary paper allocations and executions.
async function install(page: Page, baseURL: string, state: ReferenceFixture) {
  page.on('pageerror', error => state.diagnostics.push(error.message))
  page.on('console', message => {if (['error', 'warning'].includes(message.type())) state.diagnostics.push(message.text())})
  page.on('requestfailed', request => request.failure()?.errorText === 'net::ERR_ABORTED' ? undefined : state.diagnostics.push(`Failed ${request.url()}`))
  page.on('response', response => {if (response.status() >= 400) state.diagnostics.push(`HTTP ${response.status()} ${response.url()}`)})
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.origin !== new URL(baseURL).origin || request.method() !== 'GET') {
      state.diagnostics.push(`Forbidden request ${request.method()} ${url.href}`)
      return route.abort()
    }
    if (!path.startsWith('/api/')) return route.continue()
    const now = Date.now(), at = new Date(state.entryAt ?? now - 100).toISOString(), bar = new Date(state.entryAt !== undefined
      ? Math.floor(state.entryAt / 900000) * 900000 - (state.formingSignal ? 0 : 900000) : now - 16 * 60000).toISOString()
    const until = new Date(state.expired ? now - 1000 : now + 120000).toISOString()
    let json: unknown
    if (path === '/api/v1/auth/session') json = {authentication_required: true, user_id: 'signals-owner', desk_access: true, desk_write: false}
    else if (path.includes('/conversations/')) json = {conversations: [], messages: []}
    else if (path.endsWith('/desk')) json = {latest: {session, written: `${session}T23:47:45Z`, grades: Object.fromEntries(names.map(ticker => [ticker, {grade: state.publishedPlan ? ticker.startsWith('BUY') ? 'A' : 'C' : 'B'}])),
      targets: {policy: 'grade-led-learned-sizing/1', weights: {BUYLOW: .99, BUYHIGH: 0, SELLHIGH: 0}}, actions: state.publishedPlan
        ? names.map(ticker => ({ticker, grade: ticker.startsWith('BUY') ? 'A' : 'C', grade_signal: ticker.startsWith('BUY') ? 'buy' : 'sell', signal_session: session, signal_basis: 'observed_close_grade'}))
        : [{ticker: 'BUYHIGH', last_close: 127.5}], book: [], briefs: {}, regime: {exposure: 1, flags: []}}, sessions: [session]}
    else if (path.endsWith('/model-allocation')) json = state.publicationV2
      ? {version: 'strategy-model-allocation/2', status: 'available', policy: 'grade-led-learned-sizing/1', session: '2026-10-19',
        observed_at: '2026-10-19T23:49:42Z', as_of: at, published_at: at, valid_until: state.allocationUntil ?? until,
        strategy_identity: 'd'.repeat(64), snapshot_id: 'e'.repeat(64), receipt_sha256: 'f'.repeat(64), basis: 'account_independent_unit_capital_targets',
        ...(state.recordedMode ? {recorded_history_version:'strategy-recorded-entries/1'} : {}),
        account_basis: 'no_account_inputs', timing_basis: 'nightly_position_size_not_immediate_trade_size',
        entry_assessment: state.numerical ? {version:'strategy-numerical-entries/1',status:'available',snapshot_id:(state.numericalForeign ? '0' : 'e').repeat(64),
          publication_receipt_sha256:'f'.repeat(64),strategy_identity:'d'.repeat(64),receipt_sha256:'a'.repeat(64),
          session:new Date(state.entryAt ?? now).toLocaleDateString('en-CA',{timeZone:'America/New_York'}),
          completed_at:new Date(Math.floor((state.entryAt ?? now-100)/900000)*900000).toISOString(),generated_at:at,
          valid_until:new Date(Math.floor((state.entryAt ?? now-100)/900000)*900000+900000).toISOString(),
          sizing_basis:'fresh_unit_capital_allocation_not_account_trade_quantity',feed:'iex',account_inputs:false,
          rows:{BUYHIGH:{state:state.numerical,action:'Buy',size_weight:.143,quote_at:at,valid_until:new Date(state.numericalExpired ? now-1000 : now+20000).toISOString(),
            evidence:{grade:'A',inputs_as_of:'2026-10-19',model_position_size:.143,completed_candle_at:new Date(Math.floor((state.entryAt ?? now-100)/900000)*900000).toISOString(),
              features:{ema_21_distance:-.0944},reason:'Original numerical timing recommendation',observed_price:102,waiting_log_utility:state.numerical==='execute' ? -.001 : .001}}}} : undefined,
        identity: {schema: 'strategy-recommendation-publication/1', strategy_identity: 'd'.repeat(64), session: '2026-10-19', policy: 'grade-led-learned-sizing/1', basis: 'account_independent_unit_capital_targets'},
        grade_signals: Object.fromEntries([...names, 'NEWNAME'].map(ticker => [ticker, {action: ticker.startsWith('BUY') || ticker === 'NEWNAME' ? 'buy' : ticker === 'SELLLOW' || state.noSellSignals ? 'avoid' : 'sell',
          grade: ticker.startsWith('BUY') || ticker === 'NEWNAME' ? 'A' : 'C', session: state.independentSignalWrong ? 'foreign' : '2026-10-19', basis: 'observed_close_grade'}])),
        rows: Object.fromEntries([...names, 'NEWNAME'].map(ticker => {const weight = ticker === 'BUYHIGH' ? .143 : ticker === 'NEWNAME' ? .075 : 0; return [ticker, {target_weight: weight,
          evidence: {inputs_as_of: '2026-10-19', grade: ticker.startsWith('BUY') || ticker === 'NEWNAME' ? 'A' : 'C', model_position_size: weight,
            features: {ema_21_distance: -.0944, ema_63_distance: .015}, reason: 'Original independently published model size', timing_state: 'awaiting_completed_regular_candle'}}]}))}
      : state.independentSizing
      ? {version: 'strategy-model-allocation/1', status: 'available', policy: 'grade-led-learned-sizing/1', session,
        observed_at: `${session}T23:47:45Z`, as_of: at, valid_until: state.allocationUntil ?? until,
        record_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64), basis: 'account_independent_unit_capital_targets',
        grade_signals: Object.fromEntries(names.map(ticker => [ticker, {action: ticker === 'SELLLOW' ? 'avoid' : ticker.startsWith('BUY') ? 'buy' : 'sell',
          grade: ticker.startsWith('BUY') ? 'A' : 'C', session: state.independentSignalWrong ? 'foreign' : session, basis: 'observed_close_grade'}])),
        rows: {BUYHIGH: {target_weight: state.targetWeight ?? .025}, BUYLOW: {target_weight: 0}, SELLHIGH: {target_weight: 0}, SELLLOW: {target_weight: 0}}}
      : state.allocationMissing
      ? {version: 'published-model-allocation/1', status: 'unavailable', reason: 'Published model allocation could not be verified', rows: {}}
      : {version: 'published-model-allocation/1', status: 'available', policy: 'grade-led-learned-sizing/1', session,
        observed_at: state.allocationWrong ? '2026-10-12T23:47:45Z' : `${session}T23:47:45Z`, as_of: at,
        valid_until: state.allocationUntil ?? until, record_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64),
        basis: 'original_published_strategy_allocation_not_trade_quantity',
        rows: {BUYHIGH: {target_weight: .025}, BUYLOW: {target_weight: 0}, SELLHIGH: {target_weight: state.publishedPlan ? 0 : .1}}}
    else if (path.endsWith('/live')) {
      state.liveReads++
      json = {as_of: at, decision_session: session, market_status: {phase: state.phase, as_of: at},
        quotes: Object.fromEntries(names.map(ticker => [ticker, {last: 102, bar, as_of: at}])),
        grades_live: Object.fromEntries(names.map(ticker => [ticker, {grade_live: ticker.startsWith('SELL') ? 'C' : 'A', score_live: .5}])),
        grade_valid_until: Object.fromEntries(names.map(ticker => [ticker, until])), technical: {}, technical_detail: {},
        opportunities: {status: 'complete', rows: Object.fromEntries(names.filter(ticker => ticker !== 'MISSING').map(ticker => [ticker, {
          ticker, entry: ticker.startsWith('BUY') ? 'ready' : ticker === 'WAIT' ? 'wait' : 'avoid', exit: ticker.startsWith('SELL') ? 'review' : 'hold',
          entry_priority: ticker === 'BUYLOW' ? 'low' : 'high', exit_priority: ticker === 'SELLLOW' ? 'low' : 'high',
          reason: ticker.startsWith('SELL') ? 'Failed rebounds and broken support warrant a downside review.' : 'Buyers defended support; entry awaits only the stated confirmation.',
          confirmation: 'hold_above', confirmation_ref: 'vwap', invalidation_ref: 'support',
          levels: {vwap: {label: 'session VWAP', price: 100}, support: {label: 'daily support', price: 98}},
          price: 102, bar, generated_at: at, valid_until: state.signalUntil ?? until, status: 'model_assessment',
        }]))}}
    } else if (path.endsWith('/session-prices')) json = {as_of: at, signal_scope: 'regular-session', session: 'regular', quotes: Object.fromEntries(names.map(ticker => [ticker, {
      price: state.lost && ticker === 'BUYHIGH' ? 97 : 102, session: 'regular', status: state.quoteMissing ? 'unavailable' : 'fresh', feed: 'iex', at, valid_until: until}]))}
    else if (path.endsWith('/paper')) json = state.paper ? {reason: 'Paper account unavailable'} : {equity: 100000, cash: 0, positions: [{symbol: 'BUYLOW', qty: 999, market_value: 99900}],
      plan: {orders: [{symbol: 'BUYHIGH', action: 'SELL', qty: 777, state: 'filled', terminal: true, client_order_id: 'contrary-paper'}]},
      model_decisions: {status: 'unavailable', rows: {}}}
    else if (path.endsWith('/holdings')) json = {holdings: []}
    else if (path.includes('/history/')) json = {rows: [{date: session, grade: 'C', said: true}, {date: '2026-10-14', grade: 'A', said: false}, {date: '2026-10-15', grade: 'B', said: false}], fills: [], backtest: null}
    else if (path.includes('/chart/')) {
      const frame = url.searchParams.get('timeframe') ?? 'daily'
      state.chartFrames?.push(frame)
      const entryDay = new Date(state.entryAt ?? now).toLocaleDateString('en-CA', {timeZone: 'America/New_York'})
      const dates = state.currentSessionBars && frame !== '15m' ? [...new Set(frame === 'weekly' ? [entryDay] : ['2026-10-19', entryDay])]
        : frame === 'weekly' ? ['2026-10-09', '2026-10-16'] : frame === '15m' ? [session] : ['2026-10-09', '2026-10-12', session, '2026-10-14', '2026-10-15']
      const timedBars = frame === '15m' && state.entryAt !== undefined ? [-2, -1, 0].map(offset => {
        const start = Math.floor(state.entryAt! / 900000) * 900000 + offset * 900000
        return {date: new Date(start).toLocaleDateString('en-CA', {timeZone: 'America/New_York'}), time: new Date(start).toISOString(), open: 100, high: 105, low: 99, close: 102, volume: 100}
      }) : null
      const sessions = Number(url.searchParams.get('sessions') ?? 10)
      if (frame === '15m') state.chartSessions?.push(sessions)
      const zoomBars = frame === '15m' && state.zoomHistory ? zoomCandles(sessions) : null
      json = {ticker: path.split('/').pop(), timeframe: frame, adjusted: frame !== '15m', basis: 'Explicit independent acceptance price candles', sessions, sessions_requested: sessions, bars: zoomBars ?? timedBars ?? dates.map(date => ({date, time: `${date}T14:00:00Z`, open: 100, high: 105, low: 99, close: 102, volume: 100})), overlays: {}, levels: {}, entries: []}
    }
    else if (path.endsWith('/recommendations') && path.includes('/strategy-simulation/')) {
      state.recordedReads=(state.recordedReads??0)+1
      const ticker=path.split('/').at(-2),earlier=url.searchParams.has('before')
      if (state.recordedMode==='late') await new Promise(resolve=>setTimeout(resolve,500))
      const originalAt=(state.entryAt??now)-5000-(earlier ? 900000 : 0)
      const completed=Math.floor(originalAt/900000)*900000
      json={schema:'strategy-recorded-entries/1',ticker,current_instruction:false,account_inputs:false,recommendation_not_fill:true,
        strategy_identity:(state.recordedMode==='foreign' ? '0' : 'd').repeat(64),coverage_from:new Date(completed).toISOString(),indexed_through:at,
        next_cursor:state.recordedMode==='paged' && !earlier ? 'earlier-page' : null,
        items:ticker==='BUYHIGH' ? [{id:(earlier ? '8' : '7').repeat(64),ticker,at:new Date(originalAt).toISOString(),completed_at:new Date(completed).toISOString(),
          snapshot_id:(earlier ? 'b' : 'e').repeat(64),strategy_identity:'d'.repeat(64),action:'Buy',size_weight:.143,valid_until:new Date(completed+900000).toISOString(),original_bytes_sha256:'9'.repeat(64)}] : []}
    }
    else if (path.endsWith('/recommendation') && path.includes('/strategy-simulation/')) {
      state.originalReads=(state.originalReads??0)+1
      if (state.originalDelay) await new Promise(resolve=>setTimeout(resolve,state.originalDelay))
      const ticker=path.split('/').at(-2),weight=state.originalMode==='size' ? .2 : .143
      json={schema:'strategy-recorded-entry/1',ticker,current_instruction:false,recommendation_not_fill:true,account_inputs:false,verified_against_installed_economics:true,
        original_bytes_sha256:(state.recordedMode==='bytes' ? '0' : '9').repeat(64),
        original:{ticker,action:'Buy',at:new Date((state.entryAt??now)-(state.originalMode || state.recordedMode ? 5000 : 0)-(state.recordedMode && url.searchParams.get('snapshot_id')==='b'.repeat(64) ? 900000 : 0)).toISOString(),
          completed_at:url.searchParams.get('completed_at'),snapshot_id:state.originalMode==='foreign' ? '0'.repeat(64) : url.searchParams.get('snapshot_id'),
          strategy_identity:'d'.repeat(64),size_weight:weight,evidence:{grade:'A',inputs_as_of:'2026-10-19',model_position_size:weight,
            reason:state.originalMode || state.recordedMode ? 'Original saved timing decision before refresh' : 'Original numerical timing recommendation',
            observed_price:state.originalMode || state.recordedMode ? 99 : 102,features:{ema_21_distance:state.originalMode || state.recordedMode ? -.22 : -.0944},waiting_log_utility:-.002}}}
    }
    else if (path.includes('/strategy-simulation/')) json = {schema: 'latest-strategy-simulation/1', ticker: path.split('/').pop(), policy: state.simulationPolicy ?? 'earlier-policy',
      start: session, through: '2026-10-15', counterfactual: true, real_orders: false, splits: [], decisions: [
        {id: 'target-buy', ticker: path.split('/').pop(), date: '2026-10-09', at: '2026-10-09T20:05:00Z', action: 'BUY', target_weight: .02, weight: .02,
          evidence: {reason: 'Grade-permitted model allocation increase', inputs_as_of: '2026-10-08', grade: 'A', model_position_size: .02, features: {ema_21_distance: .062, ema_63_distance: .1, return_20: .08}, observed_price: 98, waiting_log_utility: -.0002}},
        {id: 'target-sell', ticker: path.split('/').pop(), date: '2026-10-12', at: '2026-10-12T20:05:00Z', action: 'SELL', target_weight: 0, weight: .02,
          evidence: {reason: 'Grade below A; exit the simulated position', inputs_as_of: '2026-10-09', grade: 'B', model_position_size: 0, features: {ema_21_distance: -.031}, timing_reason: 'mandatory_grade_exit'}},
        ...(state.denseMarkers ? zoomCandles(60).slice(-60,-10).map((bar,index) => ({id:`dense-${index}`,ticker:path.split('/').pop(),date:bar.date,
          at:new Date(Date.parse(bar.time)+1000).toISOString(),valid_until:new Date(Date.parse(bar.time)+900000).toISOString(),
          action:index%2 ? 'SELL' : 'BUY',target_weight:.02,weight:.02,
          evidence:{grade:'A',inputs_as_of:'2026-10-08',model_position_size:.02,features:{ema_21_distance:-.01},reason:'Original dense-fixture recommendation'}})) : []),
      ],
      trades: [{id: 'sim-buy', date: '2026-10-14', at: '2026-10-14T14:00:00Z', action: 'BUY', qty: 7, price: 101}, {id: 'sim-sell', date: '2026-10-15', at: '2026-10-15T15:00:00Z', action: 'SELL', qty: 5, price: 102}], targets: [], latest_target: .02, latest_holding: 2, provenance: {cost_bps: 10, basis: 'account_independent_unit_capital_targets', source_record_sha256: (state.simulationIdentityWrong ? 'c' : 'a').repeat(64),
        ...(state.publicationV2 ? {config_sha256: '1'.repeat(64), verified_against_installed_strategy:state.installedHistory, strategy_identity: (state.simulationIdentityWrong ? 'c' : 'd').repeat(64),
          strategy_contract: {schema: 'strategy-history-economics-binding/1', strategy_identity: 'd'.repeat(64), history_sha256: '2'.repeat(64), audit_sha256: '3'.repeat(64), source_record_sha256: 'a'.repeat(64), config_sha256: '1'.repeat(64)}} : {})}}
    else if (path.includes('/live/read/')) json = {read: 'Buyers defended support.', lines: {short: [], medium: [], long: []}, data_at: bar, read_at: at, stale: false}
    else if (path.includes('/earnings/')) json = {read: null}
    else {
      state.diagnostics.push(`Unspecified ${path}`)
      return route.fulfill({status: 418, json: {detail: 'Unexpected route'}})
    }
    return route.fulfill({json:referenceFixture(json,path,state,at,now)})
  })
}

// A still-A model reduction is a Sell, with its positive trade size separate from the remaining position.
test('Standing reference trim shows a positive Sell and separate position',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH displayed grade',{exact:true})).toHaveText('A')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('13.0%')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  await board.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(1)
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Sell · Size 13.0%')
    await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 14.3%')
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('')
  }
  expect(state.diagnostics).toEqual([])
})

// Distinguish an unconfirmed positive model reduction from a publication containing no Sell objective.
test('Best sells distinguishes a pending reduction from no model sell signal',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',numericalExpired:true,referenceMode:'trim',referenceObserved:true,entryAt:Date.now()-100})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await page.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(0)
  await expect(board.getByRole('status')).toHaveText('No confirmed sell signals yet.')
  await expect(board).not.toContainText('No sell signals in the current strategy publication.')
  expect(state.diagnostics).toEqual([])
})

// Keep an observed model reduction identical in the list and every current chart header.
test('Observed reference Sell size and position agree across chart frames',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceObserved:true,entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('13.0%')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Sell · Size 13.0%')
    await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 14.3%')
  }
  expect(state.diagnostics).toEqual([])
})

// A resolved model attempt must stop repeating the trade while preserving its original chart recommendation.
test('Observed reference resolved attempt preserves original Sell without repeating it',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceObserved:true,referenceResolved:true,recordedMode:'original',entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  await expect(board).toContainText('15-minute signals · '+new Date(state.entryAt!).toLocaleDateString('en-CA',{timeZone:'America/New_York'}))
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Wait · Size —')
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('Sell · Size 13.0%')
  }
  await dialog.getByText('Recommendations',{exact:true}).click()
  await dialog.locator('button[data-recommendation-id^="recorded:"]').click()
  const details=dialog.getByRole('region',{name:'Recommendation details',exact:true})
  await expect(details).toContainText('Sell · Size 13.0%')
  await expect(details).toContainText('Original saved timing decision before refresh')
  await expect(details).toContainText('Model position 27.3% → 14.3%')
  await expect(details).toContainText('Acting now matched or exceeded the model’s expected net growth from waiting one 15-minute candle.')
  expect(state.diagnostics).toEqual([])
})

// A damaged model-book receipt cannot recover a Sell from the older grade-only presentation.
test('Observed reference malformed book cannot fall back to a Sell',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'exit',referenceObserved:true,referenceBookInvalid:true,entryAt:Date.now()-100})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('Signal coverage')).toContainText('Recommendations unavailable')
  expect(state.diagnostics).toEqual([])
})

// An unchanged short-lived quote keeps the last observed Sell visible until the next poll while the chart stops authorizing it.
test('Observed reference quote expiry retains the last answer without blinking',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceObserved:true,
    entryAt:Date.now()-100,currentSessionBars:true,numericalQuoteUntil:new Date(Date.now()+3000).toISOString()})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Sell · Size 13.0%')
  await page.waitForTimeout(3500)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('13.0%')
  await expect(board.getByLabel('BUYHIGH verdict cell',{exact:true})).toContainText('refreshing')
  await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Wait · Size —')
  expect(state.diagnostics).toEqual([])
})

// A missing grade in one stock cannot erase an independently validated recommendation elsewhere.
test('Standing reference unknown grade does not erase the whole universe',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',referenceUnknown:true,entryAt:Date.now()-100})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('13.0%')
  await expect(board.getByLabel('MISSING verdict',{exact:true})).toHaveText('Do nothing')
  expect(state.diagnostics).toEqual([])
})

// Full exits sell a positive amount while retaining an explicitly zero resulting model position.
test('Standing reference exit never renders Sell zero percent',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'exit',entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('20.0%')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('0.0%')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Sell · Size 20.0%')
  await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 0.0%')
  expect(state.diagnostics).toEqual([])
})

// Expired quotes and foreign publication identities cannot become reference sells through the legacy grade fallback.
test('Standing reference expired and foreign evidence cannot produce immediate Sell',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'exit',numericalExpired:true,entryAt:Date.now()-100})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  state.numericalExpired=false;state.numericalForeign=true
  await refresh(page,state)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await board.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(0)
  expect(state.diagnostics).toEqual([])
})

// A genuine micro-adjustment is not rounded to zero or mistaken for the whole desired position.
test('Standing reference tiny Buy keeps its separate model position',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'buy',entryAt:Date.now()-100})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Buy')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('<0.1%')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  expect(state.diagnostics).toEqual([])
})

// One original recorded Sell survives all chart frames and restores its saved reason rather than the current quote.
test('Standing reference original Sell is clickable once across chart frames',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',referenceMode:'trim',recordedMode:'original',entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('Sell · Size 13.0%')
  }
  await dialog.getByText('Recommendations',{exact:true}).click()
  await expect(dialog.locator('button[data-recommendation-id^="recorded:"]')).toHaveCount(1)
  await dialog.locator('button[data-recommendation-id^="recorded:"]').click()
  const details=dialog.getByRole('region',{name:'Recommendation details',exact:true})
  await expect(details).toContainText('Sell · Size 13.0%')
  await expect(details).toContainText('Original saved timing decision before refresh')
  await expect(details).toContainText('Model position size 14.3%')
  expect(state.diagnostics).toEqual([])
})

// Supply complete weekday candle geometry so zoom checks exercise hundreds of real canvas points.
function zoomCandles(sessions: number) {
  const days: number[] = []
  for (let day = Date.parse(`${session}T00:00:00Z`); days.length < sessions; day -= 86400000) {
    if (![0, 6].includes(new Date(day).getUTCDay())) days.unshift(day)
  }
  return days.flatMap(day => Array.from({length: 26}, (_, slot) => {
    const price = 100 + Math.sin(day / 86400000 + slot / 26) * 5
    return {date: new Date(day).toISOString().slice(0, 10), time: new Date(day + 13.5 * 3600000 + slot * 900000).toISOString(), open: price, high: price + 1, low: price - 1, close: price + .5, volume: 100}
  }))
}

// Supply fresh evidence without modifying the wall clock or any real account.
function fixture(): ReferenceFixture {
  return {phase: 'open', paper: false, lost: false, expired: false, quoteMissing: false, liveReads: 0, diagnostics: []}
}

// Complete a real refresh before inspecting the new signal state.
async function refresh(page: Page, state: Fixture) {
  const prior = state.liveReads
  await page.getByRole('button', {name: 'Refresh', exact: true}).click()
  await expect.poll(() => state.liveReads).toBeGreaterThan(prior)
}

// Disclose the frozen-model replay beside every chart frame and its original simulated recommendation.
test('Historical chart discloses current-model replay limits without changing original sizes',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,phase:'closed',installedHistory:true,simulationPolicy:'grade-led-learned-sizing/1'})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const chart=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await chart.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    const basis=chart.getByLabel('BUYHIGH replay basis',{exact:true})
    await expect(basis).toBeVisible()
    await expect(basis).toContainText('Historical replay · current model')
    await expect(basis).toContainText('Models were not refitted at each past date.')
    await expect(basis).toContainText('not out-of-sample validation or advice published at that time')
    await expect(chart.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 14.3%')
  }
  await chart.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:'D',exact:true}).click()
  await chart.getByText('Recommendations',{exact:true}).click()
  await chart.locator('button[data-recommendation-id="target-buy"]').click()
  const detail=chart.getByRole('region',{name:'Recommendation details',exact:true})
  await expect(detail).toContainText('Current-model replay; not out-of-sample evidence.')
  await expect(detail).toContainText('Buy · Size 2.0%')
  await expect(detail).toContainText('2026-10-08 close')
  await expect(detail).toContainText('6.20%')
  expect(state.diagnostics).toEqual([])
})

// A saved original recommendation must not inherit the simulated replay's training provenance.
test('Recorded original recommendations are not relabelled as current-model replay',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,numerical:'execute',numericalExpired:true,
    entryAt:Date.now()-100,currentSessionBars:true,recordedMode:'original'})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const chart=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await chart.getByText('Recommendations',{exact:true}).click()
  await chart.locator('button[data-recommendation-id^="recorded:"]').click()
  const detail=chart.getByRole('region',{name:'Recommendation details',exact:true})
  await expect(detail).toContainText('Recorded recommendation')
  await expect(detail).toContainText('Observed IEX midpoint $99.00')
  await expect(detail).not.toContainText('Current-model replay; not out-of-sample evidence.')
  await expect(chart.getByLabel('BUYHIGH replay basis',{exact:true})).toHaveCount(0)
  expect(state.diagnostics).toEqual([])
})

// Separate the current desired position from trade-sized historical markers and an unconfirmed next-session entry.
test('Current position and historical trade sizes have distinct labels on every timeframe',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,phase:'post-market',installedHistory:true,simulationPolicy:'grade-led-learned-sizing/1',currentSessionBars:true,entryAt:Date.now()-100})
  await install(page,baseURL!,state);await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByRole('columnheader',{name:'Position %',exact:true})).toHaveCount(1)
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Buy · Size —')
    await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 14.3%')
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).not.toContainText('Size 14.3%')
  }
  expect(state.diagnostics).toEqual([])
})

// Keep the table and every chart headline consistent about a next-session plan without inventing a current entry.
test('Next-session Buy labels match the table on every chart without creating an entry marker',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,phase:'post-market',currentSessionBars:true,entryAt:Date.now()-100})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Buy')
  await expect(board.getByLabel('BUYHIGH verdict cell',{exact:true})).toContainText('next session')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Buy · Size —')
    await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 14.3%')
    await expect(dialog.getByLabel('BUYHIGH chart plan timing',{exact:true})).toHaveText('Next session')
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('')
  }
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  state.phase='open'
  await refresh(page,state)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH verdict cell',{exact:true})).not.toContainText('next session')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Wait · Size —')
  await expect(dialog.getByLabel('BUYHIGH current chart position',{exact:true})).toHaveText('Position 14.3%')
  await expect(dialog.getByLabel('BUYHIGH chart plan timing',{exact:true})).toHaveCount(0)
  expect(state.diagnostics).toEqual([])
})

// Preserve saved recommendations after quote expiry and reload, restoring original reasons on every chart frame.
test('Recorded entries survive expiry and reload with original size and technical reasons',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',numericalExpired:true,entryAt:Date.now()-100,currentSessionBars:true,recordedMode:'original'})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  for (const frame of ['D','W','15m']) {
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('Buy · Size 14.3%')
  }
  await dialog.getByText('Recommendations',{exact:true}).click()
  await dialog.locator('button[data-recommendation-id^="recorded:"]').click()
  const detail=dialog.getByRole('region',{name:'Recommendation details',exact:true})
  await expect(detail).toContainText('Recorded recommendation')
  await expect(detail).toContainText('Observed IEX midpoint $99.00')
  await expect(detail).toContainText('-22.00%')
  await expect(detail).not.toContainText('$102.00')
  await page.reload()
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('Buy · Size 14.3%')
  await expect.poll(()=>state.recordedReads??0).toBeGreaterThanOrEqual(2)
  expect(state.diagnostics).toEqual([])
})

for (const mode of ['foreign','bytes'] as const) {
  // Reject a foreign history identity or a substituted original body without showing refreshed reasons as historical.
  test(`Recorded entries refuse ${mode} identity`,async ({page,baseURL})=>{
    const state=fixture()
    Object.assign(state,{publicationV2:true,numerical:'wait',entryAt:Date.now()-100,currentSessionBars:true,recordedMode:mode})
    await install(page,baseURL!,state)
    await page.goto('/?deskView=strategy#desk')
    await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
    await dialog.getByText('Recommendations',{exact:true}).click()
    if (mode==='foreign') {
      await expect(dialog).toContainText('Recorded recommendations unavailable.')
      await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('')
    } else {
      await dialog.locator('button[data-recommendation-id^="recorded:"]').click()
      await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Original recommendation unavailable.')
      await expect(dialog).not.toContainText('Observed IEX midpoint $102.00')
    }
    expect(state.diagnostics).toEqual([])
  })
}

// Keep separately recorded decisions on the same candle separate while paging without duplicates.
test('Recorded entries page original decisions without duplicate markers or changed details',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'wait',entryAt:Date.now()-100,currentSessionBars:true,recordedMode:'paged'})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await dialog.getByText('Recommendations',{exact:true}).click()
  await expect(dialog.locator('button[data-recommendation-id^="recorded:"]')).toHaveCount(1)
  await dialog.getByRole('button',{name:'Earlier recorded recommendations',exact:true}).click()
  await expect(dialog.locator('button[data-recommendation-id^="recorded:"]')).toHaveCount(2)
  await expect(dialog.getByRole('button',{name:'Earlier recorded recommendations',exact:true})).toHaveCount(0)
  await dialog.locator('button[data-recommendation-id="recorded:'+ '8'.repeat(64)+'"]').click()
  await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Observed IEX midpoint $99.00')
  expect(state.diagnostics).toEqual([])
})

// Keep a late original-history response behind the ticker that requested it.
test('Late recorded history cannot cross a ticker switch',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'wait',entryAt:Date.now()-100,currentSessionBars:true,recordedMode:'late'})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  await expect.poll(()=>state.recordedReads??0).toBeGreaterThan(0)
  await page.getByRole('dialog',{name:'BUYHIGH history',exact:true}).getByRole('button',{name:'Close',exact:true}).click()
  await page.getByRole('button',{name:'BUYLOW',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYLOW history',exact:true})
  await expect.poll(()=>state.recordedReads??0).toBeGreaterThan(1)
  await page.waitForTimeout(650)
  await expect(dialog.getByLabel('BUYLOW target chart markers',{exact:true})).toHaveText('')
  expect(state.diagnostics).toEqual([])
})

// Use the publication's own dated universe even when the funded record is older and disagrees.
test('Numerical entries drive the action and 15m marker, with quote and snapshot refusal', async ({page, baseURL}) => {
  const state = fixture()
  state.publicationV2=true
  state.numerical='execute'
  state.entryAt=Date.now()-100
  state.simulationPolicy='grade-led-learned-sizing/1'
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Buy')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  await expect(board).toContainText(`15-minute signals · ${new Date(state.entryAt).toLocaleDateString('en-CA',{timeZone:'America/New_York'})}`)
  await expect(board).not.toContainText('Awaiting 15-minute entries')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await dialog.getByRole('button',{name:'15m',exact:true}).click()
  await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toContainText('Buy · Size 14.3%')
  await dialog.getByText('Recommendations',{exact:true}).click()
  await dialog.locator('button[data-recommendation-id^="current:"]').click()
  await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Observed IEX midpoint $102.00')
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  state.numerical='wait'
  await refresh(page,state)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board).toContainText('15-minute signals')
  state.numerical='execute';state.numericalForeign=true
  await refresh(page,state)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board).toContainText('Awaiting 15-minute entries')
  state.numericalForeign=false;state.numericalExpired=true
  await refresh(page,state)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board).toContainText('15-minute signals')
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('14.3%')
  expect(state.diagnostics).toEqual([])
})

// Every chart frame must wait for the same numerical entry and mark its actual session after confirmation.
test('Daily weekly and 15m charts require the same confirmed numerical entry',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'wait',entryAt:Date.now()-100,currentSessionBars:true})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  for (const button of ['D','W','15m']) {
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:button,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Wait · Size 14.3%')
    await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toHaveText('')
  }
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  state.numerical='execute'
  await refresh(page,state)
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Buy')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  for (const button of ['D','W','15m']) {
    await dialog.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:button,exact:true}).click()
    await expect(dialog.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Buy · Size 14.3%')
    const markers=dialog.getByLabel('BUYHIGH target chart markers',{exact:true})
    await expect(markers).toHaveText('Buy · Size 14.3%')
    const day=new Date(state.entryAt!).toLocaleDateString('en-CA',{timeZone:'America/New_York'})
    const expected=button==='15m' ? Math.floor(state.entryAt!/900000)*900 : Date.parse(day+'T00:00:00Z')/1000
    await expect(markers).toHaveAttribute('data-marker-times',String(expected))
  }
  expect(state.diagnostics).toEqual([])
})

for (const mode of ['original','foreign','size'] as const) {
  // Read the saved first decision instead of refreshed quote evidence, refusing foreign identity or altered model size.
  test(`Current marker restores original numerical recommendation: ${mode}`,async ({page,baseURL})=>{
    // Start this identity test inside a real candle; dedicated expiry cases cover its deadline.
    const remaining=900000-Date.now()%900000
    if(remaining<10000) await new Promise(resolve=>setTimeout(resolve,remaining+250))
    const state=fixture()
    Object.assign(state,{publicationV2:true,numerical:'execute',entryAt:Date.now()-100,simulationPolicy:'grade-led-learned-sizing/1',originalMode:mode})
    await install(page,baseURL!,state)
    await page.goto('/?deskView=strategy#desk')
    await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
    await dialog.getByRole('button',{name:'15m',exact:true}).click()
    await dialog.getByText('Recommendations',{exact:true}).click()
    await dialog.locator('button[data-recommendation-id^="current:"]').click()
    const detail=dialog.getByRole('region',{name:'Recommendation details',exact:true})
    await expect.poll(()=>state.originalReads??0).toBe(1)
    if (mode==='original') {
      await expect(detail).toContainText('Recorded recommendation')
      await expect(detail).toContainText('Original saved timing decision before refresh')
      await expect(detail).toContainText('Observed IEX midpoint $99.00')
      await expect(detail).toContainText('-22.00%')
      await expect(detail).toContainText('Buy · Size 14.3%')
      await expect(detail).not.toContainText('$102.00')
    } else {
      await expect(detail).toContainText('Original recommendation unavailable.')
      await expect(detail).not.toContainText('Original saved timing decision before refresh')
      await expect(detail).not.toContainText('$102.00')
    }
    expect(state.diagnostics).toEqual([])
  })
}

// A late response cannot reopen a closed explanation or prevent a fresh explicitly selected read.
test('Late original-recommendation response stays behind its closed selection',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,numerical:'execute',entryAt:Date.now()-100,simulationPolicy:'grade-led-learned-sizing/1',originalMode:'original',originalDelay:500})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await dialog.getByRole('button',{name:'15m',exact:true}).click()
  await dialog.getByText('Recommendations',{exact:true}).click()
  const response=page.waitForResponse(reply=>reply.url().includes('/recommendation?'))
  await dialog.locator('button[data-recommendation-id^="current:"]').click()
  await expect.poll(()=>state.originalReads??0).toBe(1)
  await dialog.getByRole('button',{name:'Close recommendation details',exact:true}).click()
  await (await response).finished()
  await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toHaveCount(0)
  state.originalDelay=0
  await dialog.locator('button[data-recommendation-id^="current:"]').click()
  await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Observed IEX midpoint $99.00')
  await expect.poll(()=>state.originalReads??0).toBe(2)
  expect(state.diagnostics).toEqual([])
})

// Use the publication's own dated universe even when the funded record is older and disagrees.
test('Installed strategy history remains visible when current allocation expires', async ({page, baseURL}) => {
  const state=fixture()
  state.publicationV2=true;state.installedHistory=true;state.simulationPolicy='grade-led-learned-sizing/1'
  state.allocationUntil=new Date(Date.now()-1000).toISOString()
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await expect(page.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('Unavailable')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await expect(dialog.getByLabel('BUYHIGH target chart markers',{exact:true})).toContainText('Buy · Size 2.0%')
  await dialog.getByText('Recommendations',{exact:true}).click()
  await dialog.locator('button[data-recommendation-id="target-buy"]').click()
  await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('6.20%')
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  state.simulationIdentityWrong=true
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  await expect(dialog).toContainText('Size history unavailable')
  expect(state.diagnostics).toEqual([])
})

// A published grade exit needs a fresh regular quote but never invents an account's sell amount.
test('Independent grade exits show Sell without a fabricated zero-percent trade', async ({page, baseURL}) => {
  const state=fixture();state.publicationV2=true
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('SELLHIGH verdict',{exact:true})).toHaveText('Sell')
  await expect(board.getByLabel('SELLHIGH model size',{exact:true})).toHaveText('0.0%')
  await expect(board.getByLabel('SELLHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  state.quoteMissing=true
  await refresh(page,state)
  await expect(board.getByLabel('SELLHIGH verdict',{exact:true})).toHaveText('Do nothing')
  expect(state.diagnostics).toEqual([])
})

// Use the publication's own dated universe even when the funded record is older and disagrees.
test('Independent publication uses its own universe, grades and clocks without a funded record', async ({page, baseURL}) => {
  const state = fixture()
  state.publicationV2 = true
  state.paper = true
  state.phase = 'post-market'
  state.expired = true
  state.allocationUntil = new Date(Date.now() + 120000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board).toContainText('All names · 7')
  await expect(board.getByLabel('BUYHIGH displayed grade', {exact: true})).toHaveText('A')
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toHaveText('14.3%')
  await expect(board.getByLabel('NEWNAME model size', {exact: true})).toHaveText('7.5%')
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Buy')
  await expect(board).toContainText('2026-10-19')
  state.independentSignalWrong = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toContainText('Unavailable')
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Do nothing')
  expect(state.diagnostics).toEqual([])
})

// Keep original explanations under a validated stable strategy identity and refuse a foreign economics binding.
test('Independent publication retains original history through a stable economics contract', async ({page, baseURL}) => {
  const state = fixture()
  state.publicationV2 = true
  state.phase = 'closed'
  state.simulationPolicy = 'grade-led-learned-sizing/1'
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await dialog.getByText('Recommendations', {exact: true}).click()
  await dialog.locator('button[data-recommendation-id="target-buy"]').click()
  const details = dialog.getByRole('region', {name: 'Recommendation details'})
  await expect(details).toContainText('Buy · Size 2.0%')
  await expect(details).toContainText('6.20%')
  await expect(details).toContainText('2026-10-08 close')
  await expect(details).not.toContainText('-9.44%')
  await dialog.getByRole('button', {name: 'W', exact: true}).click()
  await expect(details).toContainText('6.20%')
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  state.simulationIdentityWrong = true
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  await expect(dialog).toContainText('Size history unavailable')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 2.0%')
  expect(state.diagnostics).toEqual([])
})

// Refuse to present the unrelated display assessment as the numerical timing model's entry.
test('Independent publication does not invent numerical entries from display judgments', async ({page, baseURL}) => {
  const state = fixture()
  state.publicationV2 = true
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toHaveText('14.3%')
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Do nothing')
  await board.getByRole('button', {name: 'details for BUYHIGH', exact: true}).click()
  await expect(board.getByLabel('BUYHIGH signal details', {exact: true})).toContainText('numerical 15-minute entry')
  expect(state.diagnostics).toEqual([])
})

// Rank both directions by original model priority without paper sizes or account inputs.
test('All names ranks independent buy and sell signals, with matching details', async ({page, baseURL}) => {
  const state = fixture()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board).toBeVisible({timeout: 5000})
  await board.getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'BUYHIGH')
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toContainText('Buy')
  await expect(board.getByLabel('BUYHIGH signal strength', {exact: true})).toHaveText('High')
  await expect(board).not.toContainText('777 sh')
  await expect(board).not.toContainText('999 sh')
  await board.getByRole('button', {name: 'Best sells', exact: true}).click()
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'SELLHIGH')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toContainText('Sell')
  await expect(board.getByLabel('SELLHIGH signal strength', {exact: true})).toHaveText('High')
  await board.getByRole('button', {name: 'details for SELLHIGH', exact: true}).click()
  const detail = board.getByLabel('SELLHIGH signal details', {exact: true})
  await expect(detail).toContainText('Failed rebounds and broken support')
  await expect(detail).toContainText('$98.00')
  await expect(detail).toContainText('Not a short-sale signal')
  await expect(detail).toContainText('Valid until')
  state.paper = true
  await refresh(page, state)
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'SELLHIGH')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toContainText('Sell')
  await page.reload()
  await page.getByRole('region', {name: 'All names signals', exact: true}).getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(page.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'BUYHIGH')
  expect(state.diagnostics).toEqual([])
})

// Render real model percentages separately from price movement and keep the full chart on the same dated price.
test('All names dates the comparison and shows independent model size in row and chart', async ({page, baseURL}) => {
  const state = fixture()
  state.paper = true
  state.quoteMissing = true
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board.getByRole('columnheader', {name: 'Position size %', exact: true})).toBeVisible()
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toContainText('2.5% target')
  await expect(board.getByLabel('BUYLOW model size', {exact: true})).toContainText('0.0% target')
  await expect(board.getByLabel('BUYHIGH session price', {exact: true})).toContainText('-20.0% vs Oct 13 close')
  await board.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history', exact: true})
  await expect(dialog.getByLabel('BUYHIGH session price', {exact: true})).toContainText('$102.00 regular')
  await expect(dialog.getByLabel('BUYHIGH session price', {exact: true})).not.toContainText('$127.50')
  await expect(dialog.getByLabel('BUYHIGH model size', {exact: true})).toContainText('2.5% target')
  expect(state.diagnostics).toEqual([])
})

// Expire a numeric target without a network refresh and reject a different original plan on refresh.
test('All names withholds expired or foreign model percentages without hiding signal evidence', async ({page, baseURL}) => {
  const state = fixture()
  state.allocationUntil = new Date(Date.now() + 7000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const size = page.getByLabel('BUYHIGH model size', {exact: true})
  await expect(size).toContainText('2.5% target')
  await expect(size).toContainText('Unavailable', {timeout: 10000})
  await expect(page.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Buy')
  state.allocationUntil = undefined
  state.allocationWrong = true
  await refresh(page, state)
  await expect(size).toContainText('Unavailable')
  state.allocationWrong = false
  state.allocationMissing = true
  await refresh(page, state)
  await expect(size).toContainText('could not be verified')
  expect(state.diagnostics).toEqual([])
})

// Show independent percentages even when the funded account cannot produce a usable allocation.
test('All names shows strategy percentages despite unavailable paper funding', async ({page, baseURL}) => {
  const state = fixture()
  state.phase = 'post-market'
  state.expired = true
  state.publishedPlan = true
  state.independentSizing = true
  state.paper = true
  state.allocationMissing = true
  state.allocationUntil = new Date(Date.now() + 120000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toHaveText('2.5%')
  await expect(board.getByRole('columnheader', {name: 'Action', exact: true})).toHaveCount(1)
  await expect(board.getByRole('columnheader', {name: 'Buy', exact: true})).toHaveCount(0)
  await expect(board.getByRole('columnheader', {name: 'Sell', exact: true})).toHaveCount(0)
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Buy')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toHaveText('Sell')
  // Check the exact existing palette in both themes instead of assuming the wall clock selects light mode.
  for (const theme of ['light', 'dark'] as const) {
    await page.evaluate(value => window.localStorage.setItem('anios.theme', value), theme)
    await page.reload()
    await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveCSS('color', theme === 'light' ? 'rgb(36, 138, 61)' : 'rgb(48, 209, 88)')
    await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toHaveCSS('color', theme === 'light' ? 'rgb(180, 35, 24)' : 'rgb(255, 105, 97)')
  }
  await expect(board.getByLabel('SELLHIGH model size', {exact: true})).toHaveText('0.0%')
  await expect(board.getByLabel('SELLHIGH trade size', {exact: true})).toHaveText('—')
  await expect(board.getByRole('columnheader', {name: 'Position %', exact: true})).toHaveCount(1)
  await expect(board.getByLabel('SELLLOW verdict', {exact: true})).toHaveText('Do nothing')
  await expect(board.getByLabel('SELLLOW model size', {exact: true})).toHaveText('0.0%')
  await expect(board.getByRole('columnheader', {name: 'Size %', exact: true})).toHaveCount(1)
  await expect(board.getByRole('columnheader', {name: 'Strength', exact: true})).toHaveCount(0)
  await expect(board).not.toContainText('Account-independent model')
  await expect(board).toContainText('Next-session actions')
  await expect(board.locator('tbody tr').first()).toHaveAttribute('data-ticker', 'BUYHIGH')
  await board.getByRole('button', {name: 'Best sells', exact: true}).click()
  await expect(board.locator('tbody tr').first()).toHaveAttribute('data-ticker', 'SELLHIGH')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toHaveText('Sell')
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveCount(0)
  await board.getByRole('button', {name: 'All names', exact: true}).click()
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Buy')
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toHaveText('2.5%')
  await board.getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(board.locator('tbody tr').first()).toHaveAttribute('data-ticker', 'BUYHIGH')
  await board.getByRole('button', {name: 'All names', exact: true}).click()
  state.independentSignalWrong = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toContainText('Unavailable')
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Do nothing')
  expect(state.diagnostics).toEqual([])
})

// Keep authenticated next-session directions visible without inventing a live trigger after the close.
test('All names shows a dated published plan after regular chart assessments expire', async ({page, baseURL}) => {
  const state = fixture()
  state.phase = 'post-market'
  state.expired = true
  state.publishedPlan = true
  state.allocationUntil = new Date(Date.now() + 120000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toHaveText('Buy')
  await expect(board.getByLabel('BUYHIGH displayed grade', {exact: true})).toHaveText('A · plan')
  await expect(board.getByLabel('BUYHIGH model size', {exact: true})).toContainText('2.5% target')
  await expect(board.getByLabel('BUYLOW verdict', {exact: true})).toHaveText('Do nothing')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toHaveText('Sell')
  await expect(board.getByLabel('SELLHIGH model size', {exact: true})).toContainText('0.0% target')
  await expect(board.getByLabel('Signal coverage')).toContainText('3 published plan rows')
  await expect(board).not.toContainText('Buy now')
  await board.getByRole('button', {name: 'details for BUYHIGH', exact: true}).click()
  await expect(board.getByLabel('BUYHIGH signal details')).toContainText('Published plan')
  await expect(board.getByLabel('BUYHIGH signal details')).toContainText('not an immediate action')
  await board.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history', exact: true})
  await expect(dialog.getByLabel('BUYHIGH signal details')).toContainText('Buy')
  await expect(dialog.getByLabel('BUYHIGH model size', {exact: true})).toContainText('2.5% target')
  expect(state.diagnostics).toEqual([])
})

// Expire the plan on its own deadline and reject foreign evidence without upgrading it to a current signal.
test('All names withdraws closed-session plan directions when allocation authority is lost', async ({page, baseURL}) => {
  const state = fixture()
  state.phase = 'post-market'
  state.expired = true
  state.publishedPlan = true
  state.allocationUntil = new Date(Date.now() + 7000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const buy = page.getByLabel('BUYHIGH verdict', {exact: true})
  await expect(buy).toHaveText('Buy')
  // The board promises one of three words, so a lost authority reads as Do nothing with the reason beside it.
  await expect(buy).toHaveText('Do nothing', {timeout: 10000})
  const cell = page.getByLabel('BUYHIGH verdict cell', {exact: true})
  await expect(cell).toContainText(/unavailable|publication required/i)
  state.allocationUntil = new Date(Date.now() + 120000).toISOString()
  state.allocationWrong = true
  await refresh(page, state)
  await expect(buy).toHaveText('Do nothing')
  await expect(cell).toContainText(/unavailable|publication required/i)
  state.allocationWrong = false
  state.phase = 'open'
  await refresh(page, state)
  await expect(buy).toHaveText('Do nothing')
  await expect(cell).toContainText(/unavailable|publication required/i)
  expect(state.diagnostics).toEqual([])
})

// Expire the model judgment on its original deadline without a refresh or a changed grade/quote.
test('All names expires its own signal receipt without a network update', async ({page, baseURL}) => {
  const state = fixture()
  state.signalUntil = new Date(Date.now() + 7000).toISOString()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const buy = page.getByLabel('BUYHIGH verdict', {exact: true})
  await expect(buy).toContainText('Buy')
  await expect(buy).toContainText('Do nothing', {timeout: 10000})
  await expect(page.getByLabel('BUYHIGH verdict cell', {exact: true})).toContainText(/unavailable|publication required/i)
  await expect(page.getByLabel('BUYHIGH displayed grade', {exact: true})).toHaveText('A')
  expect(state.diagnostics).toEqual([])
})

// Display only source-matched model target percentages and grade changes, without account trade labels.
test('Stock charts show Buy and Sell target percentages with grade changes only', async ({page, baseURL}, info) => {
  await page.addInitScript(() => {
    const state = window as Window & {targetDraws?: string[]}
    state.targetDraws = []
    const original = CanvasRenderingContext2D.prototype.fillText
    // Capture actual labels painted inside the chart instead of trusting the accessible text mirror.
    CanvasRenderingContext2D.prototype.fillText = function (...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && state.targetDraws!.length < 10000) state.targetDraws!.push(args[0])
      return original.apply(this, args)
    }
  })
  const state = fixture()
  state.independentSizing = true
  state.publishedPlan = true
  state.simulationPolicy = 'grade-led-learned-sizing/1'
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await expect(dialog.getByRole('checkbox', {name: 'Grade changes', exact: true})).toBeChecked()
  await expect(dialog.getByRole('checkbox', {name: 'Buy / Sell sizes', exact: true})).toBeChecked()
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).toContainText('Buy · Size 2.0%')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).toContainText('Sell · Size 2.0%')
  await expect.poll(() => page.evaluate(() => (window as Window & {targetDraws?: string[]}).targetDraws)).toEqual(expect.arrayContaining(['Buy · Size 2.0%', 'Sell · Size 2.0%', 'C→A', 'A→B']))
  // This fixture confirms an entry today, but its old price candles cannot receive today's marker.
  await expect(dialog.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Buy · Size 2.5%')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 2.5%')
  await expect(dialog).not.toContainText('BUY 7 sh')
  await expect(dialog).not.toContainText('SELL 5 sh')
  await expect(dialog.getByRole('checkbox', {name: 'Actual paper executions', exact: true})).toHaveCount(0)
  await expect(dialog.getByLabel('BUYHIGH grade signals', {exact: true})).toContainText('2 grade changes marked')
  await dialog.getByRole('checkbox', {name: 'Buy / Sell sizes', exact: true}).uncheck()
  await expect(dialog.getByRole('checkbox', {name: 'Grade changes', exact: true})).toBeChecked()
  await dialog.getByRole('checkbox', {name: 'Buy / Sell sizes', exact: true}).check()
  await expect(dialog.getByRole('region', {name: 'BUYHIGH paper order'})).toHaveCount(0)
  await info.attach('target-chart', {body: await page.screenshot(), contentType: 'image/png'})
  await dialog.getByRole('button', {name: 'W', exact: true}).click()
  await expect(dialog.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', 'weekly')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).toContainText('Sell · Size 2.0%')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 2.5%')
  await dialog.getByRole('button', {name: '15m', exact: true}).click()
  await expect(dialog.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', '15m')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).toHaveText('')
  await expect(dialog.getByLabel('BUYHIGH grade signals', {exact: true})).toContainText('0 grade changes')
  state.targetWeight = .143
  await page.reload()
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  await expect(page.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Buy · Size 14.3%')
  await expect(page.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 14.3%')
  await expect(page.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 2.5%')
  expect(state.diagnostics).toEqual([])
})

// Refuse to present an earlier allocator's simulated shares as current-strategy performance.
test('Stock charts withhold an incompatible historical simulation', async ({page, baseURL}) => {
  const state = fixture()
  state.independentSizing = true
  state.publishedPlan = true
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await expect(dialog).toContainText('Size history unavailable')
  // Current entry confirmation is independent of whether the chart has a matching current-session candle.
  await expect(dialog.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Buy · Size 2.5%')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).toHaveText('')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 2.0%')
  await expect(dialog.getByLabel('BUYHIGH simulated chart markers', {exact: true})).toHaveCount(0)
  await expect(dialog).not.toContainText('BUY 7 sh')
  await expect(dialog.getByLabel('BUYHIGH grade signals', {exact: true})).toContainText('2 grade changes marked')
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  state.simulationPolicy = 'grade-led-learned-sizing/1'
  state.simulationIdentityWrong = true
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  await expect(dialog).toContainText('Size history unavailable')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 2.0%')
  await dialog.getByRole('button', {name: 'Close', exact: true}).click()
  await page.getByRole('button', {name: 'SELLLOW', exact: true}).click()
  await expect(page.getByLabel('SELLLOW target chart markers', {exact: true})).toHaveText('')
  await expect(page.getByLabel('SELLLOW current chart target', {exact: true})).toHaveCount(0)
  expect(state.diagnostics).toEqual([])
})

// Read the original snapshot behind each historical action instead of substituting today's analysis.
test('Historical marker details show the original technical evidence and action size', async ({page, baseURL}) => {
  const state = fixture()
  state.independentSizing = true
  state.publishedPlan = true
  state.phase = 'closed'
  state.simulationPolicy = 'grade-led-learned-sizing/1'
  state.targetWeight = .000001
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await dialog.getByText('Recommendations', {exact: true}).click()
  await expect(dialog.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Wait · Size <0.1%')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size <0.1%')
  await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).not.toContainText('Buy · Size 0.0%')
  await dialog.locator('button[data-recommendation-id="target-buy"]').click()
  const details = dialog.getByRole('region', {name: 'Recommendation details'})
  await expect(details).toContainText('Buy · Size 2.0%')
  await expect(details).toContainText('2026-10-08 close')
  await expect(details).toContainText('Price vs 21-session EMA')
  await expect(details).toContainText('6.20%')
  await expect(details).toContainText('$98.00')
  await expect(details).not.toContainText('Buyers defended support')
  await dialog.locator('button[data-recommendation-id="target-sell"]').click()
  await expect(details).toContainText('Sell · Size 2.0%')
  await expect(details).toContainText('Grade B')
  await expect(details).toContainText('Below-A exit at the next open')
  await expect(details).toContainText('-3.10%')
  await expect(details).not.toContainText('6.20%')
  await expect(details).not.toContainText('Sell · Size 0.0%')
  await dialog.getByRole('button', {name: 'Close recommendation details', exact: true}).click()
  await expect(details).toHaveCount(0)
  expect(state.diagnostics).toEqual([])
})

// Click the actual painted fifteen-minute marker and inspect its original, dated explanation.
test('15m historical marker click opens original evidence at the completed-candle time', async ({page, baseURL}) => {
  await page.addInitScript(() => {
    const state = window as Window & {markerPaints?: {x:number; y:number}[]}
    state.markerPaints = []
    const original = CanvasRenderingContext2D.prototype.fillText
    // Observe the actual painted label and convert its bitmap position to browser coordinates.
    CanvasRenderingContext2D.prototype.fillText = function(text, x, y, maxWidth) {
      if (text === 'Buy · Size 1.7%') {
        const matrix = this.getTransform(), rect = this.canvas.getBoundingClientRect()
        state.markerPaints!.push({x:rect.x+(matrix.a*x+matrix.c*y+matrix.e)*rect.width/this.canvas.width, y:rect.y+(matrix.b*x+matrix.d*y+matrix.f)*rect.height/this.canvas.height})
      }
      return maxWidth === undefined ? original.call(this, text, x, y) : original.call(this, text, x, y, maxWidth)
    }
  })
  const state = fixture()
  state.independentSizing = true
  state.publishedPlan = true
  state.phase = 'closed'
  await install(page, baseURL!, state)
  await page.route('**/strategy-simulation/BUYHIGH', route => route.fulfill({json:{schema:'latest-strategy-simulation/1',ticker:'BUYHIGH',policy:'grade-led-learned-sizing/1',start:'2026-10-08',through:'2026-10-09',counterfactual:true,real_orders:false,
    provenance:{basis:'account_independent_unit_capital_targets',source_record_sha256:'a'.repeat(64)},targets:[],trades:[],splits:[],
    grade_rows:[{date:'2026-10-07',grade:'B',said:false},{date:'2026-10-08',at:'2026-10-09T13:30:00Z',grade:'A',said:false}],
    decisions:[{id:'timed-original',ticker:'BUYHIGH',date:'2026-10-09',at:'2026-10-09T14:15:00Z',valid_until:'2026-10-09T14:30:00Z',action:'BUY',weight:.017,target_weight:.025,evidence:{reason:'Original model allocation increase',grade:'A',inputs_as_of:'2026-10-08',features:{ema_21_distance:.032},observed_price:101,waiting_log_utility:-.0001}}]}}))
  await page.route('**/chart/BUYHIGH?**', route => {
    const frame = new URL(route.request().url()).searchParams.get('timeframe') ?? 'daily'
    const bars = ['13:30','13:45','14:00','14:15','14:30','14:45','15:00'].map(clock => ({date:'2026-10-09',time:`2026-10-09T${clock}:00Z`,open:100,high:103,low:99,close:101,volume:100}))
    return route.fulfill({json:{ticker:'BUYHIGH',timeframe:frame,bars:frame === '15m' ? bars : [bars[0]],overlays:{},levels:{},entries:[]}})
  })
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog = page.getByRole('dialog',{name:'BUYHIGH history'})
  await dialog.getByRole('button',{name:'15m',exact:true}).click()
  const markers = dialog.getByLabel('BUYHIGH target chart markers',{exact:true})
  await expect(markers).toContainText('Buy · Size 1.7%')
  await expect(markers).toHaveAttribute('data-marker-times',String(Date.parse('2026-10-09T14:15:00Z')/1000))
  await expect(dialog.getByLabel('BUYHIGH grade signals',{exact:true})).toContainText('1 grade changes')
  await expect.poll(() => page.evaluate(() => (window as Window & {markerPaints?: unknown[]}).markerPaints?.length ?? 0)).toBeGreaterThan(0)
  const point = await page.evaluate(() => (window as Window & {markerPaints?: {x:number;y:number}[]}).markerPaints!.at(-1)!)
  await page.mouse.click(point.x+8,point.y-4)
  const details = dialog.getByRole('region',{name:'Recommendation details'})
  await expect(details).toContainText('Buy · Size 1.7%')
  await expect(details).toContainText('Original model allocation increase')
  await expect(details).toContainText('2026-10-08 close')
  await expect(details).toContainText('3.20%')
  expect(state.diagnostics).toEqual([])
})

// Explain the actual account-independent model workflow rather than the retired personal-sizing flow.
test('Trader audit guide describes model sizes and retrospective chart actions',async ({page,baseURL})=>{
  const state=fixture();state.publicationV2=true
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'How to use this page',exact:true}).click()
  const guide=page.getByRole('region',{name:'Strategy guide',exact:true})
  await expect(guide).toContainText('Size % is the buy or sell amount.')
  await expect(guide).toContainText('Position % is the model’s desired total position.')
  await expect(guide).toContainText('Historical markers are retrospective simulations')
  await expect(guide).not.toContainText('Sizes belong to optional personal sizing')
  await expect(guide).not.toContainText('High, Medium and Low')
  expect(state.diagnostics).toEqual([])
})

// Keep the observation time visible when the selected quote is explicitly stale.
test('Trader audit stale compact prices are visibly dated in both list and chart',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,phase:'closed'})
  await install(page,baseURL!,state)
  await page.route('**/session-prices',route=>{
    const now=Date.now(),at=new Date(now-30000).toISOString()
    return route.fulfill({json:{as_of:new Date(now).toISOString(),signal_scope:'regular-session',session:'pre-market',
      quotes:Object.fromEntries(names.map(ticker=>[ticker,{price:103,at,feed:'iex',status:'stale',valid_until:new Date(now-1).toISOString(),session:'pre-market'}]))}})
  })
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByLabel('BUYHIGH session price',{exact:true})).toContainText('last pre-market')
  await expect(board.getByLabel('BUYHIGH session price',{exact:true})).toContainText('ET')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  await expect(page.getByRole('dialog').getByLabel('BUYHIGH session price',{exact:true})).toContainText('last pre-market')
  await expect(page.getByRole('dialog').getByLabel('BUYHIGH session price',{exact:true})).toContainText('ET')
  expect(state.diagnostics).toEqual([])
})

// Preserve authenticated saved stock navigation when the current publication reader withholds its expired rows.
test('Unavailable publication keeps saved stocks and charts without current sizes or actions',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,phase:'closed',installedHistory:true,simulationPolicy:'grade-led-learned-sizing/1'})
  await install(page,baseURL!,state)
  // Return the actual unavailable reader shape, which deliberately contains no grades or target rows.
  await page.route('**/desk/model-allocation',async route=>route.fulfill({json:{
    version:'strategy-model-allocation/2',status:'unavailable',policy:'grade-led-learned-sizing/1',rows:{},
    reason:'Independent strategy publication could not be verified',as_of:new Date().toISOString(),valid_until:null,
  }}))
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await expect(board.getByRole('heading',{name:`All names · ${names.length}`,exact:true})).toBeVisible()
  await expect(board).toContainText('Current recommendations unavailable. Saved stock charts remain available.')
  await expect(board.getByLabel('BUYHIGH verdict',{exact:true})).toHaveText('Do nothing')
  await expect(board.getByLabel('BUYHIGH verdict cell',{exact:true})).toContainText(/unavailable|publication required/i)
  await expect(board.getByLabel('BUYHIGH trade size',{exact:true})).toHaveText('—')
  await expect(board.getByLabel('BUYHIGH model size',{exact:true})).toHaveText('Unavailable')
  await board.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const chart=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await expect(chart).toBeVisible()
  await expect(chart).not.toContainText('Position 14.3%')
  for(const frame of ['D','W','15m']){
    await chart.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:frame,exact:true}).click()
    await expect(chart.getByLabel('BUYHIGH current chart target',{exact:true})).toHaveText('Current recommendation unavailable')
  }
  await chart.getByRole('group',{name:'Chart timeframe',exact:true}).getByRole('button',{name:'D',exact:true}).click()
  await chart.getByText('Recommendations',{exact:true}).click()
  await chart.locator('button[data-recommendation-id="target-buy"]').click()
  await expect(chart.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Buy · Size 2.0%')
  await expect(chart.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('2026-10-08 close')
  await chart.getByRole('button',{name:'Close',exact:true}).click()
  await board.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board).not.toContainText('No sell signals in the current strategy publication.')
  await expect(board.getByLabel('Signal coverage',{exact:true})).toHaveText('Recommendations unavailable')
  await board.getByRole('button',{name:'All names',exact:true}).click()
  await page.reload()
  await expect(board.getByRole('button',{name:'BUYHIGH',exact:true})).toBeVisible()
  expect(state.diagnostics).toEqual([])
})

// Distinguish unavailable publication evidence from a verified absence of sell signals.
test('Trader audit unavailable recommendations never become a no-sell claim',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,phase:'closed',expired:true})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await board.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board).toContainText('Strategy recommendations unavailable. Refresh to retry.')
  await expect(board).not.toContainText('No sell signals in the current strategy publication.')
  await expect(board.getByLabel('Signal coverage',{exact:true})).not.toContainText('0 sells')
  expect(state.diagnostics).toEqual([])
})

// Preserve Avoid and actual sell-plan context across every chart without fabricating a zero-size exit.
test('Trader audit Avoid and Sell chart headers match their list actions',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,phase:'closed'})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'SELLLOW',exact:true}).click()
  const dialog=page.getByRole('dialog')
  for(const frame of ['D','W','15m']){
    await dialog.getByRole('button',{name:frame,exact:true}).click()
    await expect(dialog.getByLabel('SELLLOW current chart target',{exact:true})).toHaveText('Avoid · Size —')
    await expect(dialog.getByLabel('SELLLOW current chart position',{exact:true})).toHaveText('Position 0.0%')
  }
  await dialog.getByRole('button',{name:'Close',exact:true}).click()
  await page.getByRole('button',{name:'SELLHIGH',exact:true}).click()
  await expect(page.getByRole('dialog').getByLabel('SELLHIGH current chart target',{exact:true})).toHaveText('Sell · Size —')
  await expect(page.getByRole('dialog').getByLabel('SELLHIGH chart plan timing',{exact:true})).toHaveText('Next session')
  expect(state.diagnostics).toEqual([])
})

// Show original numerical technical inputs in current details without inventing a causal model explanation.
test('Trader audit current details expose the original technical snapshot',async ({page,baseURL})=>{
  const state=fixture();Object.assign(state,{publicationV2:true,phase:'closed'})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'details for BUYHIGH',exact:true}).click()
  const detail=page.getByLabel('BUYHIGH signal details',{exact:true})
  await expect(detail).toContainText('Prior-close technicals · 2026-10-19')
  await expect(detail).toContainText('Price vs 21-session EMA')
  await expect(detail).toContainText('-9.44%')
  await expect(detail).toContainText('1.50%')
  await expect(detail).not.toContainText('Strength is')
  await expect(detail).not.toContainText('— ·')
  expect(state.diagnostics).toEqual([])
})

// Exclude unrelated actions from directional lists and show an honest empty sell result.
test('Directional tabs contain only matching actions and no sells means an empty list',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,phase:'closed'})
  await install(page,baseURL!,state)
  await page.goto('/?deskView=strategy#desk')
  const board=page.getByRole('region',{name:'All names signals',exact:true})
  await board.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(3)
  await expect(board.locator('tbody p[aria-label$=" verdict"]')).toHaveText(['Sell','Sell','Sell'])
  await expect(board.getByLabel('SELLLOW verdict',{exact:true})).toHaveCount(0)
  await board.getByRole('button',{name:'Best buys',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(2)
  await expect(board.locator('tbody p[aria-label$=" verdict"]')).toHaveText(['Buy','Buy'])
  state.noSellSignals=true
  await page.reload()
  await board.getByRole('button',{name:'Best sells',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(0)
  await expect(board).toContainText('No sell signals in the current strategy publication.')
  await board.getByRole('button',{name:'All names',exact:true}).click()
  await expect(board.locator('tbody tr')).toHaveCount(7)
  await expect(board.getByLabel('SELLLOW verdict',{exact:true})).toHaveText('Do nothing')
  expect(state.diagnostics).toEqual([])
})

// Keep a tiny original trade intact while explaining its changing portfolio denominator.
test('Historical size details distinguish the trade amount from the model position',async ({page,baseURL})=>{
  const state=fixture()
  Object.assign(state,{publicationV2:true,phase:'closed'})
  await install(page,baseURL!,state)
  await page.route('**/strategy-simulation/BUYHIGH',route=>route.fulfill({json:{schema:'latest-strategy-simulation/1',ticker:'BUYHIGH',policy:'grade-led-learned-sizing/1',start:session,through:session,counterfactual:true,real_orders:false,
    provenance:{basis:'account_independent_unit_capital_targets',source_record_sha256:'a'.repeat(64),config_sha256:'1'.repeat(64),strategy_identity:'d'.repeat(64),strategy_contract:{schema:'strategy-history-economics-binding/1',strategy_identity:'d'.repeat(64),history_sha256:'2'.repeat(64),audit_sha256:'3'.repeat(64),source_record_sha256:'a'.repeat(64),config_sha256:'1'.repeat(64)}},
    targets:[],trades:[],splits:[],decisions:[{id:'small-original',ticker:'BUYHIGH',date:session,at:`${session}T14:15:00Z`,action:'BUY',weight:.0007,target_weight:.25,
      evidence:{reason:'Grade-permitted model allocation increase',inputs_as_of:'2026-10-12',grade:'A',model_position_size:.25,features:{},observed_price:100}}]}}))
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'BUYHIGH history',exact:true})
  await dialog.getByText('Recommendations',{exact:true}).click()
  await dialog.locator('button[data-recommendation-id="small-original"]').click()
  const detail=dialog.getByRole('region',{name:'Recommendation details',exact:true})
  await expect(detail).toContainText('Buy · Size <0.1%')
  await expect(detail).toContainText('Model position size 25.0%')
  await expect(detail).toContainText('Trade amount as a percentage of the portfolio at that time, not the total position.')
  await expect(detail).toContainText('Buy and sell percentages from different dates cannot be added as share quantities.')
  expect(state.diagnostics).toEqual([])
})

// Exercise every chart frame without turning an unconfirmed next-session allocation into an entry.
test('Chart timeframes preserve size while all frames wait for an actual entry', async ({page, baseURL}) => {
  const state = fixture()
  state.independentSizing = true
  state.publishedPlan = true
  state.phase = 'closed'
  state.chartFrames = []
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  for (const [button, frame] of [['D', 'daily'], ['W', 'weekly'], ['15m', '15m'], ['D', 'daily'], ['15m', '15m']]) {
    await dialog.getByRole('group', {name: 'Chart timeframe', exact: true}).getByRole('button', {name: button, exact: true}).click()
    await expect(dialog.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', frame)
    await expect(dialog.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-bar-count', /^[1-9]\d*$/)
    await expect(dialog.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Wait · Size 2.5%')
    await expect(dialog.getByLabel('BUYHIGH target chart markers', {exact: true})).toHaveText('')
  }
  await dialog.getByRole('button', {name: '60 sessions', exact: true}).click()
  await expect(dialog.getByRole('button', {name: '60 sessions', exact: true})).toHaveAttribute('aria-pressed', 'true')
  expect(state.chartFrames).toEqual(expect.arrayContaining(['daily', 'weekly', '15m']))
  expect(state.diagnostics).toEqual([])
})

// Place a completed-candle entry only after its assessment, then withdraw it on lost or expired confirmation.
test('15m entry markers agree with the live action and never backdate the model size', async ({page, baseURL}) => {
  await page.addInitScript(() => {
    const state = window as Window & {entryDraws?: string[]}
    state.entryDraws = []
    const original = CanvasRenderingContext2D.prototype.fillText
    // Check the actual canvas label as well as the accessible marker time.
    CanvasRenderingContext2D.prototype.fillText = function (...args: Parameters<CanvasRenderingContext2D['fillText']>) {
      if (this.canvas.closest('[data-testid="ticker-chart-canvas"]') && state.entryDraws!.length < 10000) state.entryDraws!.push(args[0])
      return original.apply(this, args)
    }
  })
  const state = fixture()
  state.independentSizing = true
  state.publishedPlan = true
  state.entryAt = Date.now() - 2000
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  await expect(page.getByLabel('BUYHIGH verdict', {exact: true})).toContainText('Buy')
  await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
  const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
  await dialog.getByRole('button', {name: '15m', exact: true}).click()
  await expect(dialog.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', '15m')
  const markers = dialog.getByLabel('BUYHIGH target chart markers', {exact: true})
  await expect(markers).toHaveText('Buy · Size 2.5%')
  await expect(markers).toHaveAttribute('data-marker-times', String(Math.floor(state.entryAt / 900000) * 900))
  await expect.poll(() => page.evaluate(() => (window as Window & {entryDraws?: string[]}).entryDraws)).toContain('Buy · Size 2.5%')
  // Refresh through the visible board controls rather than clicking behind the modal.
  async function reassess() {
    await dialog.getByRole('button', {name: 'Close', exact: true}).click()
    await refresh(page, state)
    await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
    await dialog.getByRole('button', {name: '15m', exact: true}).click()
    await expect(dialog.getByTestId('ticker-chart-canvas')).toHaveAttribute('data-chart-timeframe', '15m')
  }
  state.lost = true
  await reassess()
  await expect(page.getByLabel('BUYHIGH verdict', {exact: true})).toContainText('Do nothing')
  await expect(dialog.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Wait · Size 2.5%')
  await expect(markers).toHaveText('')
  state.lost = false
  state.signalUntil = new Date(Date.now() - 1000).toISOString()
  await reassess()
  await expect(markers).toHaveText('')
  state.signalUntil = undefined
  state.formingSignal = true
  await reassess()
  await expect(markers).toHaveText('')
  await expect(dialog.getByLabel('BUYHIGH current chart target', {exact: true})).toHaveText('Wait · Size 2.5%')
  expect(state.diagnostics).toEqual([])
})

for (const width of [1280, 390]) {
  // Preserve all original actions while preventing unreadable same-side label collisions at a full-range zoom.
  test(`Dense strategy labels stay readable and every original decision remains inspectable at ${width}px`, async ({page,baseURL},info) => {
    await page.setViewportSize({width,height:900})
    const state=fixture()
    Object.assign(state,{independentSizing:true,publishedPlan:true,phase:'closed',zoomHistory:true,denseMarkers:true,simulationPolicy:'grade-led-learned-sizing/1'})
    await install(page,baseURL!,state)
    await page.goto('/?deskView=strategy#desk')
    await page.getByRole('button',{name:'BUYHIGH',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'BUYHIGH history'})
    await dialog.getByRole('button',{name:'15m',exact:true}).click()
    await dialog.getByRole('button',{name:'60 sessions',exact:true}).click()
    const canvas=dialog.getByTestId('ticker-chart-canvas')
    await expect(canvas).toHaveAttribute('data-bar-count','1560')
    await expect.poll(async()=>Number(await canvas.getAttribute('data-marker-count'))).toBeGreaterThanOrEqual(50)
    const labels=Number(await canvas.getAttribute('data-marker-label-count'))
    expect(labels).toBeGreaterThan(0)
    expect(labels).toBeLessThan(20)
    const spans=JSON.parse((await canvas.getAttribute('data-marker-label-spans'))!) as {left:number;right:number;position:string}[]
    const plotWidth=await canvas.locator('table td').nth(1).evaluate(el=>el.getBoundingClientRect().width)
    expect(spans.every(span=>span.left>=6 && span.right<=plotWidth-6)).toBe(true)
    for (const [index,span] of spans.entries()) for (const other of spans.slice(index+1))
      if (other.position===span.position) expect(span.right+7<=other.left || other.right+7<=span.left).toBe(true)
    // The current call's square has nothing to inspect; every replayed decision does.
    await dialog.locator('[data-marker-edge-id]:not([data-marker-kind="current"])').first().click()
    await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Original dense-fixture recommendation')
    await dialog.getByRole('button',{name:'Close recommendation details',exact:true}).click()
    await dialog.getByText('Recommendations',{exact:true}).click()
    await expect(dialog.locator('[data-recommendation-id^="dense-"]')).toHaveCount(50)
    await dialog.locator('[data-recommendation-id="dense-0"]').click()
    await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Original dense-fixture recommendation')
    await expect(dialog.getByRole('region',{name:'Recommendation details',exact:true})).toContainText('Size 2.0%')
    expect(state.diagnostics).toEqual([])
    await info.attach('readable-dense-history',{body:await dialog.screenshot(),contentType:'image/png'})
  })

  // Load older candles when zooming out, keep the plot inside data, and preserve its view on a real refresh.
  test(`15m zoom loads older candles without blank space or refresh jumps at ${width}px`, async ({page, baseURL}, info) => {
    await page.setViewportSize({width, height: 900})
    const state = fixture()
    state.independentSizing = true
    state.publishedPlan = true
    state.phase = 'closed'
    state.zoomHistory = true
    state.chartSessions = []
    await install(page, baseURL!, state)
    await page.goto('/?deskView=strategy#desk')
    await page.getByRole('button', {name: 'BUYHIGH', exact: true}).click()
    const dialog = page.getByRole('dialog', {name: 'BUYHIGH history'})
    await dialog.getByRole('button', {name: '15m', exact: true}).click()
    const canvas = dialog.getByTestId('ticker-chart-canvas')
    await expect(canvas).toHaveAttribute('data-bar-count', '260')
    const bounds = await canvas.boundingBox()
    expect(bounds).not.toBeNull()
    await page.mouse.move(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2)
    for (let step = 0; step < 35 && !state.chartSessions!.some(count => count > 10); step++) await page.mouse.wheel(0, 700)
    await expect.poll(() => state.chartSessions!.some(count => count > 10)).toBe(true)
    await dialog.getByRole('button', {name: '60 sessions', exact: true}).click()
    await expect.poll(() => state.chartSessions).toContain(60)
    await expect(canvas).toHaveAttribute('data-bar-count', '1560')
    for (let step = 0; step < 6; step++) await page.mouse.wheel(0, 1200)
    // The loaded range remains occupied; zooming cannot manufacture thousands of blank candle slots.
    await expect.poll(async () => Number(await canvas.getAttribute('data-chart-visible-bars'))).toBeLessThanOrEqual(1561)
    await expect.poll(async () => Number(await canvas.getAttribute('data-chart-visible-bars'))).toBeGreaterThan(1200)
    const from = Number(await canvas.getAttribute('data-chart-from'))
    await expect.poll(() => state.chartSessions!.filter(count => count === 60).length, {timeout: 25000}).toBeGreaterThan(1)
    await expect(canvas).toHaveAttribute('data-chart-timeframe', '15m')
    expect(Math.abs(Number(await canvas.getAttribute('data-chart-from')) - from)).toBeLessThan(2)
    expect(state.chartSessions!.every(count => count <= 60)).toBe(true)
    expect(state.diagnostics).toEqual([])
    await info.attach('zoomed-out-chart', {body: await dialog.screenshot(), contentType: 'image/png'})
  })
}

// Withhold immediate actions after quote loss, session close or expired source evidence.
test('All names separates waiting, invalidated and unavailable signals', async ({page, baseURL}) => {
  const state = fixture()
  await install(page, baseURL!, state)
  await page.goto('/?deskView=strategy#desk')
  const board = page.getByRole('region', {name: 'All names signals', exact: true})
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toContainText('Buy', {timeout: 5000})
  await expect(board.getByLabel('WAIT verdict', {exact: true})).toContainText('Do nothing')
  await expect(board.getByLabel('MISSING verdict', {exact: true})).toContainText('Do nothing')
  state.lost = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toContainText('Do nothing')
  await board.getByRole('button', {name: 'Best buys', exact: true}).click()
  await expect(board.locator('tbody tr[data-ticker]').first()).toHaveAttribute('data-ticker', 'BUYLOW')
  state.quoteMissing = true
  await refresh(page, state)
  await expect(board.locator('tbody tr')).toHaveCount(0)
  await board.getByRole('button', {name: 'All names', exact: true}).click()
  await expect(board.getByLabel('BUYLOW verdict', {exact: true})).toContainText('Do nothing')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toContainText('Do nothing')
  state.quoteMissing = false; state.phase = 'post-market'
  await refresh(page, state)
  await expect(board).not.toContainText('Buy now')
  await expect(board).not.toContainText('Sell review now')
  state.expired = true
  await refresh(page, state)
  await expect(board.getByLabel('BUYHIGH verdict', {exact: true})).toContainText('Do nothing')
  await expect(board.getByLabel('SELLHIGH verdict', {exact: true})).toContainText('Do nothing')
  expect(state.diagnostics).toEqual([])
})
