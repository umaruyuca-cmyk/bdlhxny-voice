from stockwise_analysis.contracts.analysis import AnalysisInput, AnalysisResult
from stockwise_analysis.tools.analysis_capability import PythonAnalysisCapabilityAdapter


def test_python_analysis_capability_adapter_delegates_to_engine():
    analysis_input = AnalysisInput(
        analysis_id="adapter-test",
        analysis_type="market_snapshot",
        instrument={"symbol": "600000", "name": "测试标的"},
        realtime_quote={"price": 10.0},
        historical_prices=[],
    )

    result = PythonAnalysisCapabilityAdapter().analyze(analysis_input)

    assert isinstance(result, AnalysisResult)
    assert result.analysis_id == "adapter-test"
    assert "snapshot" in result.calculated_indicators
