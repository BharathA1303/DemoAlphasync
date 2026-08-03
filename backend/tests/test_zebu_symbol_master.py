import pytest
from data_layer.ingestion.zebu_symbol_master import ZebuSymbolMasterService


def test_parse_nse_symbols():
    content = """Exchange,Token,LotSize,Symbol,TradingSymbol,Instrument,TickSize,
NSE,22,1,RELIANCE,RELIANCE-EQ,EQ,0.05,
NSE,26000,1,NIFTY,NIFTY 50,INDEX,0.05,
NSE,9999,1,TRASH,TRASH-BE,BE,0.05,
"""
    parsed = ZebuSymbolMasterService.parse_symbol_content("NSE", content)
    assert len(parsed) == 3
    rel = next(p for p in parsed if p["token"] == "22")
    assert rel["symbol"] == "RELIANCE"
    assert rel["trading_symbol"] == "RELIANCE-EQ"
    assert rel["instrument_type"] == "EQ"
    assert rel["lot_size"] == 1


def test_parse_bse_symbols_filter_f_junk():
    content = """Exchange,Token,LotSize,Symbol,TradingSymbol,Instrument,TickSize,
BSE,500325,1,RELIANCE,RELIANCE-EQ,EQ,0.05,
BSE,999123,1,1190PFL28,1190PFL28,F,0.05,
"""
    parsed = ZebuSymbolMasterService.parse_symbol_content("BSE", content)
    # The F instrument with numeric prefix should be filtered out
    assert len(parsed) == 1
    assert parsed[0]["token"] == "500325"
    assert parsed[0]["symbol"] == "RELIANCE"


def test_parse_nfo_symbols():
    content = """Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,
NFO,15687,25,NIFTY,NIFTY26SEP26C25000,26-SEP-2026,OPTIDX,CE,25000.00,0.05,
NFO,15688,25,NIFTY,NIFTY26SEPFUT,26-SEP-2026,FUTIDX,XX,0.00,0.05,
"""
    parsed = ZebuSymbolMasterService.parse_symbol_content("NFO", content)
    assert len(parsed) == 2
    opt = next(p for p in parsed if p["instrument_type"] == "OPTIDX")
    assert opt["symbol"] == "NIFTY"
    assert opt["trading_symbol"] == "NIFTY26SEP26C25000"
    assert opt["option_type"] == "CE"
    assert opt["strike"] == 25000.0
    assert opt["expiry"].strftime("%Y-%m-%d") == "2026-09-26"


def test_parse_mcx_symbols():
    content = """Exchange,Token,LotSize,GNGD,Symbol,TradingSymbol,Expiry,Instrument,OptionType,StrikePrice,TickSize,
MCX,234123,1,100,GOLD,GOLD26DECFUT,26-DEC-2026,FUTCOM,XX,0.00,1.00,
"""
    parsed = ZebuSymbolMasterService.parse_symbol_content("MCX", content)
    assert len(parsed) == 1
    gold = parsed[0]
    assert gold["symbol"] == "GOLD"
    assert gold["instrument_type"] == "FUTCOM"
    assert gold["tick_size"] == 1.0
