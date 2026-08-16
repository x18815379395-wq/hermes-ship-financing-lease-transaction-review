#!/usr/bin/env python3
"""Deterministic annual vessel finance audit model (stdlib only)."""
from __future__ import annotations
import argparse, copy, json
from pathlib import Path
EPS=1e-9

def npv(rate,flows): return sum(v/((1+rate)**i) for i,v in enumerate(flows))
def irr(flows):
    if not flows or not(any(x<0 for x in flows) and any(x>0 for x in flows)): return None
    grid=[-0.99+i*.01 for i in range(100)]+[i*.05 for i in range(401)]
    lr,lv=grid[0],npv(grid[0],flows)
    for r in grid[1:]:
        v=npv(r,flows)
        if lv*v<0:
            lo,hi=lr,r
            for _ in range(100):
                mid=(lo+hi)/2
                if npv(lo,flows)*npv(mid,flows)<=0: hi=mid
                else: lo=mid
            return (lo+hi)/2
        lr,lv=r,v
    return None

def validate(d):
    n=int(d['term_years'])
    if n<=0: raise ValueError('term_years must be positive')
    for k in ('tce_per_day','utilization','scheduled_offhire_days','daily_opex','annual_management_cost'):
        if len(d[k])!=n: raise ValueError(f'{k} must have term_years values')
    if any(x<0 or x>1 for x in d['utilization']): raise ValueError('utilization must be between 0 and 1')
    if d['purchase_price']<=0: raise ValueError('purchase_price invalid')
    for key in ('drydock_events','environmental_capex_events'):
        for e in d.get(key,[]):
            if not 1<=int(e['year'])<=n or e['cost']<0: raise ValueError(f'{key} invalid')
    debt=d.get('debt',{})
    if debt.get('amount',0)<0 or debt.get('amount',0)>d['purchase_price']: raise ValueError('debt amount invalid')
    c=d.get('reported_return_claim')
    if c:
        req=('holding_years','annual_revenue','annual_operating_expense_including_depreciation','annual_depreciation','accumulated_depreciation','gross_sale_price','reported_book_value_at_sale')
        if any(k not in c for k in req): raise ValueError('reported_return_claim missing required values')
        if int(c['holding_years'])<=0 or any(float(c[k])<0 for k in req if k!='holding_years'): raise ValueError('reported_return_claim invalid')
    v=d.get('valuation_crosscheck')
    if v:
        comps=v.get('comparables',[])
        if not comps or any(float(x.get('adjusted_price',-1))<0 or float(x.get('weight',1))<0 for x in comps): raise ValueError('valuation comparables invalid')
        req=('replacement_cost','physical_depreciation','functional_obsolescence','economic_obsolescence')
        if any(k not in v or float(v[k])<0 for k in req): raise ValueError('valuation cost approach invalid')
        if sum(float(x.get('weight',1)) for x in comps)<=EPS: raise ValueError('valuation comparable weights invalid')
    return n

def reported_return_bridge(d):
    c=d.get('reported_return_claim')
    if not c: return None
    years=int(c['holding_years']); revenue=float(c['annual_revenue']); expense=float(c['annual_operating_expense_including_depreciation']); dep=float(c['annual_depreciation']); accum=float(c['accumulated_depreciation']); sale=float(c['gross_sale_price']); book=float(c['reported_book_value_at_sale'])
    acquisition=float(c.get('initial_acquisition_cost',book+accum)); sale_costs=float(c.get('sale_costs',0)); cash_opex=expense-dep
    if cash_opex<0: raise ValueError('annual depreciation exceeds operating expense')
    annual_cash=revenue-cash_opex
    reported_op=(revenue-expense)*years; disposal=sale-book
    reported_total=reported_op+disposal
    adjusted_accounting=annual_cash*years-accum+disposal-sale_costs
    cash_profit=annual_cash*years+sale-sale_costs-acquisition
    flows=[-acquisition]+[annual_cash]*(years-1)+[annual_cash+sale-sale_costs]
    hire=float(c['reported_daily_hire']) if 'reported_daily_hire' in c else None; daily_opex=float(c['reported_daily_opex']) if 'reported_daily_opex' in c else None
    implied_revenue_days=revenue/hire if hire and hire>EPS else None; implied_opex_days=cash_opex/daily_opex if daily_opex and daily_opex>EPS else None
    return {
      'initial_acquisition_cost':acquisition,'holding_years':years,
      'reported_operating_profit_recalculated':reported_op,'reported_disposal_gain_recalculated':disposal,
      'reported_total_profit_recalculated':reported_total,'reported_roi_recalculated':reported_total/acquisition if acquisition>EPS else None,
      'cash_opex_after_removing_depreciation':cash_opex,'annual_operating_cashflow_before_capex_tax_and_financing':annual_cash,
      'cash_profit_before_tax_and_sale_costs':cash_profit,'cash_roi_before_tax_and_sale_costs':cash_profit/acquisition if acquisition>EPS else None,
      'project_irr_before_tax_and_sale_costs':irr(flows),'simple_cash_payback_years':acquisition/annual_cash if annual_cash>EPS else None,
      'accounting_profit_adjusted_for_actual_accumulated_depreciation':adjusted_accounting,
      'accounting_cash_reconciliation_gap':adjusted_accounting-reported_total,
      'annual_depreciation_times_holding_years':dep*years,'accumulated_depreciation_reported':accum,
      'implied_revenue_days_at_reported_daily_hire':implied_revenue_days,'implied_cash_opex_days_at_reported_daily_opex':implied_opex_days,
      'reported_total_profit_difference':reported_total-float(c.get('reported_total_profit',reported_total)),
      'reported_roi_difference':reported_total/acquisition-float(c.get('reported_roi',reported_total/acquisition)) if acquisition>EPS else None,
      'scope':'before tax, financing, drydock/environmental capex not included unless embedded in reported expense, and before unreported sale costs'
    }

def valuation_crosscheck(d):
    v=d.get('valuation_crosscheck')
    if not v: return None
    comps=v['comparables']; prices=[float(x['adjusted_price']) for x in comps]; weights=[float(x.get('weight',1)) for x in comps]
    simple=sum(prices)/len(prices); weighted=sum(p*w for p,w in zip(prices,weights))/sum(weights)
    replacement=float(v['replacement_cost']); physical=float(v['physical_depreciation']); functional=float(v['functional_obsolescence']); economic=float(v['economic_obsolescence'])
    cost=replacement-physical-functional-economic; gap=weighted-cost
    clean=lambda x: round(x,10)
    return {
      'comparable_count':len(comps),'market_simple_average':clean(simple),'market_weighted_average':clean(weighted),
      'market_min':clean(min(prices)),'market_max':clean(max(prices)),'market_range':clean(max(prices)-min(prices)),
      'replacement_cost':clean(replacement),'physical_depreciation':clean(physical),'functional_obsolescence':clean(functional),
      'economic_obsolescence':clean(economic),'cost_approach_value':clean(cost),'market_cost_gap':clean(gap),
      'market_cost_gap_rate_vs_market':clean(gap/weighted) if abs(weighted)>EPS else None,
      'market_cost_gap_rate_vs_cost':clean(gap/cost) if abs(cost)>EPS else None,
      'reported_market_value_difference':clean(simple-float(v.get('reported_market_value',simple))),
      'reported_cost_value_difference':clean(cost-float(v.get('reported_cost_value',cost))),
      'selection_rule':'Do not mechanically average methods; select or weight by valuation purpose, value premise, evidence quality and method applicability.'
    }

def calculate(d,f=None):
    f=f or {}; n=validate(d); tce_mult=float(f.get('tce_multiplier',1)); util_mult=float(f.get('utilization_multiplier',1)); opex_mult=float(f.get('opex_multiplier',1)); residual_mult=float(f.get('residual_multiplier',1)); extra_off=float(f.get('extra_offhire_days',0)); capex_mult=float(f.get('capex_multiplier',1))
    dry={}
    for e in d.get('drydock_events',[]):
        y=int(e['year']); rec=dry.setdefault(y,{'cost':0.0,'extra_offhire_days':0.0}); rec['cost']+=float(e['cost']); rec['extra_offhire_days']+=float(e.get('extra_offhire_days',0))
    env={}
    for e in d.get('environmental_capex_events',[]):
        y=int(e['year']); env[y]=env.get(y,0.0)+float(e['cost'])*capex_mult
    debt=d.get('debt',{}); debt_amt=float(debt.get('amount',0)); debt_rate=float(debt.get('annual_rate',0))+float(f.get('interest_rate_add',0)); tenor=min(int(debt.get('tenor_years',0)),n); principal=debt_amt/tenor if tenor else 0; debt_open=debt_amt
    rate=float(d.get('discount_rate',.1)); days=float(d.get('days_per_year',365)); years=[]; project=[-float(d['purchase_price'])]; equity=[-(float(d['purchase_price'])-debt_amt)]; dscrs=[]; cfads_debt=[]; total_rev_days=0; total_operating_cost=0; total_debt_service=0
    for y in range(1,n+1):
        de=dry.get(y,{}); off=float(d['scheduled_offhire_days'][y-1])+float(de.get('extra_offhire_days',0))+extra_off; off=min(days,max(0,off)); util=min(1,max(0,float(d['utilization'][y-1])*util_mult)); rev_days=(days-off)*util
        tce=float(d['tce_per_day'][y-1])*tce_mult; revenue=rev_days*tce; opex=days*float(d['daily_opex'][y-1])*opex_mult; mgmt=float(d['annual_management_cost'][y-1])*opex_mult; drycap=float(de.get('cost',0))*capex_mult; envcap=env.get(y,0.0); cfads=revenue-opex-mgmt-drycap-envcap
        interest=debt_open*debt_rate if y<=tenor else 0; pmt=min(principal,debt_open) if y<=tenor else 0; service=interest+pmt; close=max(0,debt_open-pmt); dscr=cfads/service if service>EPS else None
        if dscr is not None: dscrs.append(dscr); cfads_debt.append(cfads)
        residual=0
        if y==n: residual=float(d.get('residual_value',0))*residual_mult*(1-float(d.get('sale_cost_rate',0)))
        pc=cfads+residual; ec=cfads-service+residual; project.append(pc); equity.append(ec)
        years.append({'year':y,'scheduled_offhire_days':off,'utilization':util,'revenue_days':rev_days,'tce_per_day':tce,'tce_revenue':revenue,'vessel_opex':opex,'management_cost':mgmt,'drydock_capex':drycap,'environmental_capex':envcap,'cfads':cfads,'debt_opening':debt_open,'interest':interest,'principal':pmt,'debt_service':service,'dscr':dscr,'debt_closing':close,'net_residual':residual,'project_cashflow':pc,'equity_cashflow':ec})
        total_rev_days+=rev_days; total_operating_cost+=opex+mgmt+drycap+envcap; total_debt_service+=service; debt_open=close
    pv=sum(v/((1+debt_rate)**i) for i,v in enumerate(cfads_debt,1)); net_res=float(d.get('residual_value',0))*residual_mult*(1-float(d.get('sale_cost_rate',0)))
    op_be=total_operating_cost/total_rev_days if total_rev_days else None; ds_be=(total_operating_cost+total_debt_service)/total_rev_days if total_rev_days else None
    return {'years':years,'project_cashflows':project,'equity_cashflows':equity,'project_npv':npv(rate,project),'project_irr':irr(project),'equity_irr':irr(equity),'minimum_dscr':min(dscrs) if dscrs else None,'average_dscr':sum(dscrs)/len(dscrs) if dscrs else None,'llcr':pv/debt_amt if debt_amt>EPS else None,'opening_ltv':debt_amt/float(d['purchase_price']),'breakeven_tce_operating':op_be,'breakeven_tce_debt_service':ds_be,'net_residual':net_res}

def run_model(d):
    validate(d); base=calculate(d); scenarios={k:calculate(d,v) for k,v in d.get('scenarios',{}).items()}; bridge=reported_return_bridge(d); valuation=valuation_crosscheck(d); flags=[]
    if base['minimum_dscr'] is not None and base['minimum_dscr']<1: flags.append('BASE_DSCR_BELOW_1_00')
    if base['project_npv']<0: flags.append('BASE_PROJECT_NPV_NEGATIVE')
    if bridge:
        if abs(bridge['annual_depreciation_times_holding_years']-bridge['accumulated_depreciation_reported'])>EPS: flags.append('REPORTED_DEPRECIATION_PERIOD_MISMATCH')
        if 'reported_roi' in d['reported_return_claim'] and bridge['holding_years']>1: flags.append('REPORTED_ROI_IS_NOT_IRR')
        a=bridge['implied_revenue_days_at_reported_daily_hire']; b=bridge['implied_cash_opex_days_at_reported_daily_opex']
        if a is not None and b is not None and abs(a-b)>15: flags.append('REPORTED_DAY_COUNT_MISMATCH')
    if valuation:
        if valuation['comparable_count']<3: flags.append('VALUATION_FEWER_THAN_3_COMPARABLES')
        if valuation['cost_approach_value']<0: flags.append('VALUATION_DEPRECIATION_EXCEEDS_REPLACEMENT_COST')
        if abs(valuation['market_cost_gap_rate_vs_market'] or 0)>0.20: flags.append('VALUATION_MARKET_COST_GAP_ABOVE_20PCT')
        if abs(valuation['reported_market_value_difference'])>1e-6 or abs(valuation['reported_cost_value_difference'])>1e-6: flags.append('VALUATION_REPORTED_ARITHMETIC_MISMATCH')
    return {'validation':{'ok':True,'currency_unit':'same_as_input','market_defaults_used':False},'base':base,'scenarios':scenarios,'reported_return_bridge':bridge,'valuation_crosscheck':valuation,'hard_flags':flags}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('input'); ap.add_argument('--output','-o'); a=ap.parse_args(); out=run_model(json.loads(Path(a.input).read_text(encoding='utf-8'))); text=json.dumps(out,ensure_ascii=False,indent=2)
    if a.output: Path(a.output).write_text(text,encoding='utf-8')
    else: print(text)
if __name__=='__main__': main()
