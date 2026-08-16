#!/usr/bin/env python3
import importlib.util
import math
from pathlib import Path

P=Path(__file__).with_name('vessel_finance_model.py')
s=importlib.util.spec_from_file_location('m',P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def sample():
 return {
  'purchase_price':100.0,'term_years':3,'days_per_year':365,
  'tce_per_day':[0.10,0.10,0.10],'utilization':[0.9,0.9,0.9],
  'scheduled_offhire_days':[10,20,10],'daily_opex':[0.03,0.03,0.03],
  'annual_management_cost':[1,1,1],'drydock_events':[{'year':2,'cost':8.0,'extra_offhire_days':15}],
  'environmental_capex_events':[{'year':3,'cost':3.0}],
  'residual_value':60.0,'sale_cost_rate':0.05,'discount_rate':0.10,
  'debt':{'amount':60.0,'annual_rate':0.06,'tenor_years':3,'repayment':'equal_principal'},
  'scenarios':{'tce_down_40':{'tce_multiplier':0.6},'residual_down_40':{'residual_multiplier':0.6},'interest_up_200bp':{'interest_rate_add':0.02}}
 }

def test_available_days_and_tce_revenue():
 r=m.run_model(sample())['base']
 assert math.isclose(r['years'][0]['revenue_days'],(365-10)*0.9)
 assert math.isclose(r['years'][0]['tce_revenue'],31.95)
 assert r['years'][1]['revenue_days'] < r['years'][0]['revenue_days']

def test_drydock_is_cash_capex_and_offhire():
 r=m.run_model(sample())['base']
 assert r['years'][1]['drydock_capex']==8.0
 assert r['years'][1]['scheduled_offhire_days']==35
 assert r['years'][2]['environmental_capex']==3.0

def test_metrics_and_breakeven():
 r=m.run_model(sample())['base']
 assert r['project_irr'] is not None and r['equity_irr'] is not None
 assert r['minimum_dscr']>0 and r['llcr']>0
 assert r['years'][-1]['debt_closing']==0.0
 assert r['breakeven_tce_operating']>0
 assert r['breakeven_tce_debt_service']>r['breakeven_tce_operating']
 assert math.isclose(r['net_residual'],57.0)

def test_stress_cannot_improve_base():
 out=m.run_model(sample())
 assert out['scenarios']['tce_down_40']['minimum_dscr'] < out['base']['minimum_dscr']
 assert out['scenarios']['residual_down_40']['project_npv'] < out['base']['project_npv']
 assert out['scenarios']['interest_up_200bp']['minimum_dscr'] < out['base']['minimum_dscr']

def test_same_year_capex_events_are_aggregated():
 d=sample()
 d['drydock_events'].append({'year':2,'cost':2.0,'extra_offhire_days':5})
 d['environmental_capex_events'].append({'year':3,'cost':2.0})
 r=m.run_model(d)['base']
 assert math.isclose(r['years'][1]['drydock_capex'],10.0)
 assert math.isclose(r['years'][1]['scheduled_offhire_days'],40.0)
 assert math.isclose(r['years'][2]['environmental_capex'],5.0)

def test_invalid_utilization_rejected():
 d=sample(); d['utilization']=[1.1,0.9,0.9]
 try: m.run_model(d)
 except ValueError as e: assert 'utilization' in str(e)
 else: raise AssertionError('expected ValueError')

def test_reported_return_bridge_separates_depreciation_and_cash():
 d=sample(); d['reported_return_claim']={
  'holding_years':6,'annual_revenue':500.0,'annual_operating_expense_including_depreciation':180.0,
  'annual_depreciation':40.0,'accumulated_depreciation':200.0,'gross_sale_price':900.0,
  'reported_book_value_at_sale':250.0,'reported_total_profit':2570.0,'reported_roi':5.70,
  'reported_daily_hire':1.5,'reported_daily_opex':0.5}
 b=m.run_model(d)['reported_return_bridge']
 assert math.isclose(b['reported_operating_profit_recalculated'],1920.0)
 assert math.isclose(b['reported_disposal_gain_recalculated'],650.0)
 assert math.isclose(b['reported_total_profit_recalculated'],2570.0)
 assert math.isclose(b['cash_profit_before_tax_and_sale_costs'],2610.0)
 assert math.isclose(b['cash_roi_before_tax_and_sale_costs'],5.8)
 assert math.isclose(b['accounting_cash_reconciliation_gap'],40.0)
 assert b['project_irr_before_tax_and_sale_costs']>0.82
 assert math.isclose(b['implied_revenue_days_at_reported_daily_hire'],500/1.5)
 assert math.isclose(b['implied_cash_opex_days_at_reported_daily_opex'],140/0.5)

def test_return_bridge_flags_depreciation_period_mismatch():
 d=sample(); d['reported_return_claim']={
  'holding_years':6,'annual_revenue':500.0,'annual_operating_expense_including_depreciation':180.0,
  'annual_depreciation':40.0,'accumulated_depreciation':200.0,'gross_sale_price':900.0,
  'reported_book_value_at_sale':250.0,'reported_total_profit':2570.0,'reported_roi':5.70,
  'reported_daily_hire':1.5,'reported_daily_opex':0.5}
 out=m.run_model(d)
 assert 'REPORTED_DEPRECIATION_PERIOD_MISMATCH' in out['hard_flags']
 assert 'REPORTED_ROI_IS_NOT_IRR' in out['hard_flags']
 assert 'REPORTED_DAY_COUNT_MISMATCH' in out['hard_flags']

def test_valuation_crosscheck_recalculates_market_and_cost_methods():
 d=sample(); d['valuation_crosscheck']={
  'comparables':[{'adjusted_price':34.8},{'adjusted_price':35.2},{'adjusted_price':33.8}],
  'replacement_cost':37.0,'physical_depreciation':5.6,'functional_obsolescence':0.8,
  'economic_obsolescence':1.0,'reported_market_value':34.5,'reported_cost_value':29.6}
 v=m.run_model(d)['valuation_crosscheck']
 assert math.isclose(v['market_simple_average'],34.6)
 assert math.isclose(v['market_weighted_average'],34.6)
 assert math.isclose(v['cost_approach_value'],29.6)
 assert math.isclose(v['market_cost_gap'],5.0)
 assert math.isclose(v['market_cost_gap_rate_vs_market'],5/34.6)
 assert math.isclose(v['reported_market_value_difference'],0.1)

def test_valuation_crosscheck_supports_weights_and_flags_reported_error():
 d=sample(); d['valuation_crosscheck']={
  'comparables':[{'adjusted_price':34.8,'weight':0.5},{'adjusted_price':35.2,'weight':0.3},{'adjusted_price':33.8,'weight':0.2}],
  'replacement_cost':37.0,'physical_depreciation':5.6,'functional_obsolescence':0.8,
  'economic_obsolescence':1.0,'reported_market_value':34.5,'reported_cost_value':29.6}
 out=m.run_model(d); v=out['valuation_crosscheck']
 assert math.isclose(v['market_weighted_average'],34.72)
 assert 'VALUATION_REPORTED_ARITHMETIC_MISMATCH' in out['hard_flags']

if __name__=='__main__':
 tests=[v for k,v in sorted(globals().items()) if k.startswith('test_')]
 for t in tests: t()
 print(f'PASS {len(tests)}/{len(tests)}')
