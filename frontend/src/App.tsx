import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Loader2,
  Settings2,
  Play,
  Server,
  ShieldAlert,
  Wrench,
  XCircle,
} from "lucide-react";
import "./styles.css";

type Anomaly = {
  anomaly_id: string;
  service: string;
  kind: string;
  severity: string;
  start: string;
  end: string;
  summary: string;
  evidence: string[];
};

type ReactTraceStep = {
  thought: string;
  action: string;
  observation: string;
};

type DiagnosisReport = {
  report_id: string;
  markdown: string;
  root_cause?: string;
  confidence?: string;
  impact?: string;
  timeline?: string[];
  evidence?: string[];
  recommendations?: string[];
  react_trace?: ReactTraceStep[];
};

type DiagnoseResponse = {
  log_file?: string;
  anomaly_count: number;
  report_count: number;
  anomalies: Anomaly[];
  reports: DiagnosisReport[];
};

type AlertRecord = {
  alert_id: string;
  anomaly_id: string;
  service: string;
  kind: string;
  severity: string;
  summary: string;
  status: string;
  created_at: string;
  updated_at: string;
  report_id?: string;
};

type NormalizedReport = {
  rootCause: string;
  confidence: string;
  impact: string;
  timeline: string[];
  evidence: string[];
  recommendations: string[];
  reactTrace: ReactTraceStep[];
};

type ApiStatus = "checking" | "online" | "offline";
type LlmProvider = "claude" | "deepseek" | "newapi";

type LlmConfig = {
  provider: LlmProvider;
  api_key: string;
  base_url: string;
  model: string;
  timeout: number;
  api_key_set?: boolean;
};

const API_BASE = "/api";
const TOOL_COUNT = 5;
const PROVIDER_DEFAULTS: Record<LlmProvider, { base_url: string; model: string }> = {
  claude: { base_url: "", model: "claude-opus-4-6-thinking" },
  deepseek: { base_url: "https://api.deepseek.com", model: "deepseek-v4-pro" },
  newapi: { base_url: "", model: "codex-mini-latest" },
};

function App() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DiagnoseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedAnomalyId, setSelectedAnomalyId] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [showModelConfig, setShowModelConfig] = useState(false);
  const [llmConfig, setLlmConfig] = useState<LlmConfig>({
    provider: "claude",
    api_key: "",
    base_url: "",
    model: "claude-opus-4-6-thinking",
    timeout: 300,
    api_key_set: false,
  });
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelStatus, setModelStatus] = useState("");
  const [modelBusy, setModelBusy] = useState<"refresh" | "test" | "save" | "">("");

  useEffect(() => {
    let cancelled = false;

    async function checkApi() {
      try {
        const response = await fetch(`${API_BASE}/health`);
        if (!cancelled) {
          setApiStatus(response.ok ? "online" : "offline");
        }
      } catch {
        if (!cancelled) {
          setApiStatus("offline");
        }
      }
    }

    checkApi();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    loadLlmConfig();
  }, []);

  const selectedReport = useMemo(() => {
    if (!result?.reports.length) return null;
    return result.reports.find((item) => item.report_id === selectedReportId) ?? result.reports[0];
  }, [result, selectedReportId]);

  const selectedAnomaly = useMemo(() => {
    if (!result?.anomalies.length) return null;
    return result.anomalies.find((item) => item.anomaly_id === selectedAnomalyId) ?? result.anomalies[0];
  }, [result, selectedAnomalyId]);

  const reportView = useMemo(() => {
    if (!selectedReport) return null;
    return normalizeReport(selectedReport);
  }, [selectedReport]);

  async function runSampleDiagnosis() {
    setLoading(true);
    setError(null);
    setAlerts([]);
    try {
      const response = await fetch(`${API_BASE}/diagnose/sample`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data: DiagnoseResponse = await response.json();
      setResult(data);
      setSelectedReportId(data.reports[0]?.report_id ?? null);
      setSelectedAnomalyId(data.anomalies[0]?.anomaly_id ?? null);
      setApiStatus("online");
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
      setApiStatus("offline");
    } finally {
      setLoading(false);
    }
  }

  async function replaySampleLogs() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/ingest/sample`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset_state: true }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      const nextAlerts: AlertRecord[] = data.alerts || [];
      const reports: DiagnosisReport[] = data.reports || [];
      setAlerts(nextAlerts);
      setResult({
        log_file: data.log_file,
        anomaly_count: nextAlerts.length,
        report_count: reports.length,
        anomalies: nextAlerts.map(alertToAnomaly),
        reports,
      });
      setSelectedReportId(reports[0]?.report_id ?? null);
      setSelectedAnomalyId(nextAlerts[0]?.anomaly_id ?? null);
      setApiStatus("online");
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败");
      setApiStatus("offline");
    } finally {
      setLoading(false);
    }
  }

  async function loadLlmConfig() {
    try {
      const response = await fetch("/llm-config");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "加载模型配置失败");
      const provider = (data.provider || "claude") as LlmProvider;
      setLlmConfig({
        provider,
        api_key: "",
        base_url: data.base_url || "",
        model: data.model || PROVIDER_DEFAULTS[provider].model,
        timeout: data.timeout || 300,
        api_key_set: data.api_key_set,
      });
    } catch (err) {
      setModelStatus(err instanceof Error ? err.message : "加载模型配置失败");
    }
  }

  function changeProvider(provider: LlmProvider) {
    const defaults = PROVIDER_DEFAULTS[provider];
    setModelOptions([]);
    setLlmConfig((prev) => ({
      ...prev,
      provider,
      base_url: prev.provider === provider ? prev.base_url : defaults.base_url,
      model: prev.provider === provider ? prev.model : defaults.model,
    }));
  }

  async function refreshModels() {
    setModelBusy("refresh");
    setModelStatus("正在刷新模型列表...");
    try {
      const response = await fetch("/llm-config/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(modelRequestPayload(llmConfig)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "刷新模型列表失败");
      const models = data.models || [];
      setModelOptions(models);
      setModelStatus(models.length ? `已刷新 ${models.length} 个模型` : "没有获取到模型");
      if (models.length && !models.includes(llmConfig.model)) {
        setLlmConfig((prev) => ({ ...prev, model: models[0] }));
      }
    } catch (err) {
      setModelStatus(err instanceof Error ? err.message : "刷新模型列表失败");
    } finally {
      setModelBusy("");
    }
  }

  async function testModelConfig() {
    setModelBusy("test");
    setModelStatus("正在测试连接...");
    try {
      const response = await fetch("/llm-config/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(modelRequestPayload(llmConfig)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "模型连通性测试失败");
      setModelStatus(`测试通过：${data.message || "OK"}`);
    } catch (err) {
      setModelStatus(err instanceof Error ? err.message : "模型连通性测试失败");
    } finally {
      setModelBusy("");
    }
  }

  async function saveModelConfig() {
    if (!llmConfig.model.trim()) {
      setModelStatus("模型名称不能为空");
      return;
    }
    setModelBusy("save");
    setModelStatus("正在保存模型配置...");
    try {
      const response = await fetch("/llm-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(modelRequestPayload(llmConfig)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "保存模型配置失败");
      setLlmConfig({
        provider: data.provider,
        api_key: "",
        base_url: data.base_url || "",
        model: data.model,
        timeout: data.timeout,
        api_key_set: data.api_key_set,
      });
      setModelStatus("模型配置已保存，下一次诊断会自动使用。");
    } catch (err) {
      setModelStatus(err instanceof Error ? err.message : "保存模型配置失败");
    } finally {
      setModelBusy("");
    }
  }

  const anomalyCount = result?.anomaly_count ?? 0;
  const reportCount = result?.report_count ?? 0;

  return (
    <main className="page-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark">
            <Bot size={20} />
          </div>
          <div>
            <p className="kicker">ReAct Observability Agent</p>
            <h1>实时日志异常诊断工作台</h1>
          </div>
        </div>

        <div className="topbar-actions">
          <ApiBadge status={apiStatus} />
          <button className="secondary-action" onClick={() => setShowModelConfig((value) => !value)}>
            <Settings2 size={18} />
            模型配置
          </button>
          <button className="primary-action" onClick={runSampleDiagnosis} disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            {loading ? "诊断中" : "运行 sample"}
          </button>
          <button className="secondary-action" onClick={replaySampleLogs} disabled={loading}>
            <GitBranch size={18} />
            回放日志流
          </button>
        </div>
      </header>

      {showModelConfig && (
        <ModelConfigPanel
          config={llmConfig}
          setConfig={setLlmConfig}
          modelOptions={modelOptions}
          status={modelStatus}
          busy={modelBusy}
          onProvider={changeProvider}
          onRefresh={refreshModels}
          onTest={testModelConfig}
          onSave={saveModelConfig}
        />
      )}

      <section className="overview-band">
        <div className="overview-copy">
          <div className="section-label">
            <ShieldAlert size={16} />
            Log stream to root cause
          </div>
          <h2>从异常日志到可追溯证据链</h2>
          <p>
            面板聚焦日志异常、工具调用轨迹和修复建议。当前 demo 使用样例日志复现 5xx / DB timeout，并通过
            ReAct 工具链串联部署、指标、拓扑和资源证据。
          </p>
        </div>
        <div className="stat-grid">
          <StatCard icon={<AlertTriangle />} label="异常事件" value={anomalyCount.toString()} tone="danger" />
          <StatCard icon={<ShieldAlert />} label="告警记录" value={alerts.length.toString()} tone="danger" />
          <StatCard icon={<FileText />} label="诊断报告" value={reportCount.toString()} />
          <StatCard icon={<Wrench />} label="诊断工具" value={TOOL_COUNT.toString()} />
        </div>
      </section>

      {error && (
        <section className="notice error-notice" role="alert">
          <XCircle size={18} />
          <div>
            <strong>API 请求失败：{error}</strong>
            <span>请确认 FastAPI 后端已启动在 8003 端口，然后重新运行 sample 诊断。</span>
          </div>
        </section>
      )}

      {!result && !loading && (
        <section className="empty-state">
          <div className="empty-icon">
            <Database size={28} />
          </div>
          <h2>等待一次诊断运行</h2>
          <p>运行 sample 后，这里会展示异常事件、根因结论、ReAct 轨迹和原始 Markdown 报告。</p>
          <button className="secondary-action" onClick={runSampleDiagnosis}>
            <Play size={18} />
            运行 sample 诊断
          </button>
          <button className="secondary-action" onClick={replaySampleLogs}>
            <GitBranch size={18} />
            回放日志流并生成告警
          </button>
        </section>
      )}

      {loading && <LoadingState />}

      {result && selectedReport && reportView && (
        <section className="workspace-grid">
          <aside className="panel anomaly-panel">
            <PanelHeader icon={<AlertTriangle size={18} />} title="异常事件" badge={result.anomaly_count} />
            {alerts.length > 0 && <AlertLifecycle alerts={alerts} />}
            <div className="anomaly-list">
              {result.anomalies.map((anomaly) => (
                <button
                  className={`anomaly-card ${anomaly.anomaly_id === selectedAnomaly?.anomaly_id ? "active" : ""}`}
                  key={anomaly.anomaly_id}
                  onClick={() => setSelectedAnomalyId(anomaly.anomaly_id)}
                >
                  <div className="anomaly-card-head">
                    <span className="severity-pill">{anomaly.severity}</span>
                    <span>{anomaly.kind}</span>
                  </div>
                  <strong>{anomaly.service}</strong>
                  <p>{anomaly.summary}</p>
                  <small>
                    <Clock3 size={13} />
                    {formatTime(anomaly.start)} - {formatTime(anomaly.end)}
                  </small>
                </button>
              ))}
            </div>

            {selectedAnomaly && (
              <div className="evidence-box">
                <div className="mini-title">异常原始证据</div>
                {selectedAnomaly.evidence.map((item) => (
                  <code key={item}>{item}</code>
                ))}
              </div>
            )}
          </aside>

          <section className="report-column">
            <div className="panel report-panel">
              <div className="report-head">
                <PanelHeader icon={<Bot size={18} />} title="诊断报告" badge={result.report_count} />
                <div className="report-tabs" aria-label="诊断报告列表">
                  {result.reports.map((report) => (
                    <button
                      key={report.report_id}
                      className={report.report_id === selectedReport.report_id ? "active" : ""}
                      onClick={() => setSelectedReportId(report.report_id)}
                    >
                      {report.report_id}
                    </button>
                  ))}
                </div>
              </div>

              <section className="root-cause-card">
                <div>
                  <span className="confidence">{reportView.confidence || "Unknown"}</span>
                  <h2>{reportView.rootCause || "暂无结构化根因结论"}</h2>
                </div>
                <p>{reportView.impact || "报告中未提供影响范围。"}</p>
              </section>

              <div className="insight-grid">
                <InsightList icon={<Clock3 />} title="关键时间线" items={reportView.timeline} emptyText="暂无时间线" />
                <InsightList icon={<CircleDot />} title="关键证据" items={reportView.evidence} emptyText="暂无证据" />
                <InsightList icon={<CheckCircle2 />} title="修复建议" items={reportView.recommendations} emptyText="暂无建议" ordered />
              </div>
            </div>

            <div className="panel trace-panel">
              <PanelHeader icon={<GitBranch size={18} />} title="ReAct 诊断轨迹" badge={reportView.reactTrace.length} />
              <div className="trace-list">
                {reportView.reactTrace.length ? (
                  reportView.reactTrace.map((step, index) => (
                    <article className="trace-step" key={`${step.action}-${index}`}>
                      <div className="step-index">{index + 1}</div>
                      <div className="step-body">
                        <div className="step-row thought">
                          <Bot size={16} />
                          <span>{step.thought}</span>
                        </div>
                        <div className="step-row action">
                          <Code2 size={16} />
                          <code>{step.action}</code>
                        </div>
                        <div className="step-row observation">
                          <Server size={16} />
                          <span>{step.observation}</span>
                        </div>
                      </div>
                    </article>
                  ))
                ) : (
                  <p className="muted">报告中未提供 ReAct 轨迹。</p>
                )}
              </div>
            </div>

            <div className="panel markdown-panel">
              <PanelHeader icon={<FileText size={18} />} title="原始 Markdown" />
              <pre>{selectedReport.markdown}</pre>
            </div>
          </section>
        </section>
      )}
    </main>
  );
}

function modelRequestPayload(config: LlmConfig) {
  return {
    provider: config.provider,
    api_key: config.api_key.trim() ? config.api_key : null,
    base_url: config.base_url,
    model: config.model,
    timeout: Number(config.timeout) || 300,
  };
}

function alertToAnomaly(alert: AlertRecord): Anomaly {
  return {
    anomaly_id: alert.anomaly_id,
    service: alert.service,
    kind: alert.kind,
    severity: alert.severity,
    start: alert.created_at,
    end: alert.updated_at,
    summary: alert.summary,
    evidence: [`告警 ${alert.alert_id} 当前状态：${alert.status}`, alert.report_id ? `诊断报告：${alert.report_id}` : "暂无报告"],
  };
}

function AlertLifecycle({ alerts }: { alerts: AlertRecord[] }) {
  return (
    <div className="alert-lifecycle">
      <div className="mini-title">告警生命周期</div>
      {alerts.map((alert) => (
        <div className="alert-row" key={alert.alert_id}>
          <span className={`status-dot ${alert.status}`} />
          <div>
            <strong>{alert.alert_id}</strong>
            <small>{alert.status} · {alert.report_id || "no report"}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function ModelConfigPanel({
  config,
  setConfig,
  modelOptions,
  status,
  busy,
  onProvider,
  onRefresh,
  onTest,
  onSave,
}: {
  config: LlmConfig;
  setConfig: React.Dispatch<React.SetStateAction<LlmConfig>>;
  modelOptions: string[];
  status: string;
  busy: "refresh" | "test" | "save" | "";
  onProvider: (provider: LlmProvider) => void;
  onRefresh: () => void;
  onTest: () => void;
  onSave: () => void;
}) {
  return (
    <section className="model-config-panel">
      <div className="model-config-head">
        <PanelHeader icon={<Settings2 size={18} />} title="模型配置" />
        <div className="model-actions">
          <button className="secondary-action" onClick={onRefresh} disabled={busy !== ""}>
            {busy === "refresh" ? "刷新中" : "刷新模型"}
          </button>
          <button className="secondary-action" onClick={onTest} disabled={busy !== "" || !config.model.trim()}>
            {busy === "test" ? "测试中" : "测试连接"}
          </button>
          <button className="primary-action" onClick={onSave} disabled={busy !== "" || !config.model.trim()}>
            {busy === "save" ? "保存中" : "保存配置"}
          </button>
        </div>
      </div>

      <div className="model-config-grid">
        <label>
          <span>服务商</span>
          <select value={config.provider} onChange={(event) => onProvider(event.target.value as LlmProvider)}>
            <option value="claude">Claude / Anthropic</option>
            <option value="deepseek">DeepSeek</option>
            <option value="newapi">OpenAI-compatible / newapi</option>
          </select>
        </label>
        <label>
          <span>Base URL</span>
          <input
            value={config.base_url}
            onChange={(event) => setConfig((prev) => ({ ...prev, base_url: event.target.value }))}
            placeholder={PROVIDER_DEFAULTS[config.provider].base_url || "官方 Claude 可留空；中转站填写地址"}
          />
        </label>
        <label>
          <span>模型</span>
          {modelOptions.length ? (
            <select value={config.model} onChange={(event) => setConfig((prev) => ({ ...prev, model: event.target.value }))}>
              {modelOptions.map((model) => (
                <option value={model} key={model}>
                  {model}
                </option>
              ))}
            </select>
          ) : (
            <input value={config.model} onChange={(event) => setConfig((prev) => ({ ...prev, model: event.target.value }))} />
          )}
        </label>
        <label>
          <span>API Key</span>
          <input
            type="password"
            value={config.api_key}
            onChange={(event) => setConfig((prev) => ({ ...prev, api_key: event.target.value }))}
            placeholder={config.api_key_set ? "已配置，留空则不修改" : "请输入 API Key"}
          />
        </label>
        <label>
          <span>Timeout 秒</span>
          <input
            type="number"
            min={1}
            value={config.timeout}
            onChange={(event) => setConfig((prev) => ({ ...prev, timeout: Number(event.target.value) }))}
          />
        </label>
        <div className="model-current">
          <strong>{config.api_key_set ? "API Key 已配置" : "API Key 未配置"}</strong>
          <span>{config.provider} · {config.model || "未设置模型"}</span>
        </div>
      </div>
      {status && <div className="model-status">{status}</div>}
    </section>
  );
}

function ApiBadge({ status }: { status: ApiStatus }) {
  const config = {
    checking: { label: "API 检测中", icon: <Loader2 className="spin" size={15} /> },
    online: { label: "API 在线", icon: <CheckCircle2 size={15} /> },
    offline: { label: "API 离线", icon: <XCircle size={15} /> },
  }[status];

  return (
    <div className={`api-badge ${status}`}>
      {config.icon}
      <span>{config.label}</span>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone = "default",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "default" | "danger";
}) {
  return (
    <article className={`stat-card ${tone}`}>
      <div className="stat-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function PanelHeader({ icon, title, badge }: { icon: React.ReactNode; title: string; badge?: number }) {
  return (
    <div className="panel-header">
      <div>
        {icon}
        <strong>{title}</strong>
      </div>
      {typeof badge === "number" && <span>{badge}</span>}
    </div>
  );
}

function InsightList({
  icon,
  title,
  items,
  emptyText,
  ordered = false,
}: {
  icon: React.ReactNode;
  title: string;
  items: string[];
  emptyText: string;
  ordered?: boolean;
}) {
  const ListTag = ordered ? "ol" : "ul";

  return (
    <section className="insight-card">
      <div className="insight-title">
        {icon}
        <strong>{title}</strong>
      </div>
      {items.length ? (
        <ListTag>
          {items.map((item, index) => (
            <li key={`${title}-${index}`}>
              {ordered && <ChevronRight size={14} />}
              <span>{item}</span>
            </li>
          ))}
        </ListTag>
      ) : (
        <p className="muted">{emptyText}</p>
      )}
    </section>
  );
}

function LoadingState() {
  return (
    <section className="loading-grid" aria-label="诊断加载中">
      <div className="skeleton large" />
      <div className="skeleton stack">
        <span />
        <span />
        <span />
      </div>
      <div className="skeleton stack wide">
        <span />
        <span />
        <span />
        <span />
      </div>
    </section>
  );
}

function normalizeReport(report: DiagnosisReport): NormalizedReport {
  const parsed = parseMarkdownReport(report.markdown);

  return {
    rootCause: report.root_cause ?? parsed.rootCause,
    confidence: report.confidence ?? parsed.confidence,
    impact: report.impact ?? parsed.impact,
    timeline: report.timeline?.length ? report.timeline : parsed.timeline,
    evidence: report.evidence?.length ? report.evidence : parsed.evidence,
    recommendations: report.recommendations?.length ? report.recommendations : parsed.recommendations,
    reactTrace: report.react_trace?.length ? report.react_trace : parsed.reactTrace,
  };
}

function parseMarkdownReport(markdown: string): NormalizedReport {
  const rootCauseSection = getSection(markdown, "根因结论");

  return {
    confidence: extractDashValue(rootCauseSection, "置信度"),
    rootCause: extractDashValue(rootCauseSection, "根因"),
    impact: extractDashValue(rootCauseSection, "影响"),
    timeline: extractListItems(getSection(markdown, "关键时间线")),
    evidence: extractListItems(getSection(markdown, "关键证据")),
    recommendations: extractNumberedItems(getSection(markdown, "修复建议")),
    reactTrace: extractReactTrace(getSection(markdown, "ReAct 诊断轨迹")),
  };
}

function getSection(markdown: string, heading: string) {
  const lines = markdown.split(/\r?\n/);
  const startIndex = lines.findIndex((line) => line.trim() === `## ${heading}`);
  if (startIndex === -1) return "";
  const sectionLines: string[] = [];

  for (let index = startIndex + 1; index < lines.length; index += 1) {
    if (lines[index].startsWith("## ")) break;
    sectionLines.push(lines[index]);
  }

  return sectionLines.join("\n").trim();
}

function extractDashValue(section: string, label: string) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = section.match(new RegExp(`^-\\s*${escaped}：(.+)$`, "m"));
  return cleanInlineMarkdown(match?.[1] ?? "");
}

function extractListItems(section: string) {
  return section
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "))
    .map((line) => cleanInlineMarkdown(line.replace(/^- /, "")));
}

function extractNumberedItems(section: string) {
  return section
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^\d+\.\s+/.test(line))
    .map((line) => cleanInlineMarkdown(line.replace(/^\d+\.\s+/, "")));
}

function extractReactTrace(section: string): ReactTraceStep[] {
  const steps: ReactTraceStep[] = [];

  section.split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("- Thought：")) {
      steps.push({
        thought: cleanInlineMarkdown(trimmed.replace("- Thought：", "")),
        action: "",
        observation: "",
      });
      return;
    }

    const activeStep = steps[steps.length - 1];
    if (!activeStep) return;

    if (trimmed.startsWith("- Action：")) {
      activeStep.action = cleanInlineMarkdown(trimmed.replace("- Action：", ""));
    }
    if (trimmed.startsWith("- Observation：")) {
      activeStep.observation = cleanInlineMarkdown(trimmed.replace("- Observation：", ""));
    }
  });

  return steps;
}

function cleanInlineMarkdown(value: string) {
  return value.replace(/`/g, "").trim();
}

function formatTime(value: string) {
  return value.replace("T", " ").slice(0, 19);
}

export default App;
