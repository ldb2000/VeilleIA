import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Bot,
  ChartColumn,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  MoreVertical,
  NotebookPen,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-react';
import {
  chatWithReports,
  createNote,
  deleteReport,
  deleteNote,
  generateReportSummary,
  getChatMessages,
  getReportDetail,
  getReportPdfUrl,
  getReports,
  getReportSummary,
  getNotes,
  triggerReport,
} from './api';
import type { ChatMessage, Note, Report } from './api';
import './App.css';

type ContextMenuState = {
  x: number;
  y: number;
  text: string;
} | null;

type MainView = 'dashboard' | 'reports' | 'notes' | 'searches';

const NAV_ITEMS: Array<{ id: MainView; label: string; icon: typeof ChartColumn }> = [
  { id: 'dashboard', label: 'Tableau de bord', icon: ChartColumn },
  { id: 'reports', label: 'Rapports', icon: FileText },
  { id: 'notes', label: 'Notes', icon: NotebookPen },
  { id: 'searches', label: 'Recherches', icon: Search },
];

const KNOWN_PROJECTS = [
  'OpenClaw',
  'Paperclip',
  'Cline',
  'Continue',
  'Aider',
  'Void',
  'OpenHands',
  'OpenCode',
  'Roo Code',
  'Bolt.new',
  'Codeium',
  'Windsurf',
  'Cursor',
  'Claude Code',
  'Gemini CLI',
  'Ollama',
  'OpenRouter',
  'MCP',
  'vLLM',
];

function App() {
  const [reports, setReports] = useState<Report[]>([]);
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);
  const [currentView, setCurrentView] = useState<MainView>('dashboard');
  const [loading, setLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [summaryByReportId, setSummaryByReportId] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Note[]>([]);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
  const [openActionMenuId, setOpenActionMenuId] = useState<number | null>(null);
  const markdownRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchReports();
    fetchNotes();
    fetchChatHistory();
  }, []);

  useEffect(() => {
    if (!selectedReport) {
      return;
    }
    loadSummary(selectedReport.id);
  }, [selectedReport]);

  useEffect(() => {
    const closeMenus = () => {
      setContextMenu(null);
      setOpenActionMenuId(null);
    };

    window.addEventListener('click', closeMenus);
    window.addEventListener('scroll', closeMenus);
    return () => {
      window.removeEventListener('click', closeMenus);
      window.removeEventListener('scroll', closeMenus);
    };
  }, []);

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      document.body.style.setProperty('--mouse-x', `${event.clientX}px`);
      document.body.style.setProperty('--mouse-y', `${event.clientY}px`);
    };
    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  const fetchReports = async () => {
    try {
      const data = await getReports();
      setReports(data);
      setSelectedReport((current) => {
        if (current) {
          return data.find((report) => report.id === current.id) ?? data[0] ?? null;
        }
        return data[0] ?? null;
      });
    } catch (error) {
      console.error('Erreur lors du chargement des rapports :', error);
    }
  };

  const fetchNotes = async () => {
    try {
      const data = await getNotes();
      setNotes(data);
    } catch (error) {
      console.error('Erreur lors du chargement des notes :', error);
    }
  };

  const fetchChatHistory = async () => {
    try {
      const data = await getChatMessages();
      setChatHistory(data);
    } catch (error) {
      console.error('Erreur lors du chargement des recherches :', error);
    }
  };

  const loadSummary = async (reportId: number) => {
    try {
      const result = await getReportSummary(reportId);
      setSummaryByReportId((current) => ({ ...current, [reportId]: result.summary }));
    } catch {
      setSummaryByReportId((current) => {
        if (!(reportId in current)) {
          return current;
        }
        const next = { ...current };
        delete next[reportId];
        return next;
      });
    }
  };

  const handleTrigger = async () => {
    setLoading(true);
    try {
      const newReport = await triggerReport();
      setReports((current) => [newReport, ...current]);
      setSelectedReport(newReport);
      setCurrentView('reports');
    } catch (error) {
      console.error('Erreur lors du déclenchement du rapport :', error);
      alert('Impossible de générer le rapport.');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = (id: number) => {
    window.open(getReportPdfUrl(id), '_blank');
  };

  const handleDeleteReport = async (report: Report) => {
    const confirmed = window.confirm('Supprimer ce rapport ?');
    if (!confirmed) {
      return;
    }
    try {
      await deleteReport(report.id);
      const nextReports = reports.filter((item) => item.id !== report.id);
      setReports(nextReports);
      setNotes((current) => current.filter((note) => note.report_id !== report.id));
      if (selectedReport?.id === report.id) {
        setSelectedReport(nextReports[0] ?? null);
      }
    } catch (error) {
      console.error('Erreur lors de la suppression du rapport :', error);
      alert('Impossible de supprimer le rapport.');
    }
  };

  const handleGenerateSummary = async () => {
    if (!selectedReport) {
      return;
    }
    setSummaryLoading(true);
    try {
      const result = await generateReportSummary(selectedReport.id);
      setSummaryByReportId((current) => ({ ...current, [selectedReport.id]: result.summary }));
    } catch (error) {
      console.error('Erreur lors de la génération du résumé :', error);
      alert('Impossible de générer le résumé exécutif.');
    } finally {
      setSummaryLoading(false);
    }
  };

  const appendNote = async (kind: 'note' | 'detail', sourceText: string, content: string) => {
    if (!selectedReport) {
      return;
    }
    const newNote = await createNote(selectedReport.id, {
      kind,
      source_text: sourceText,
      content,
    });
    setNotes((current) => [newNote, ...current]);
  };

  const handleAddSelectionToNotes = async () => {
    if (!contextMenu?.text) {
      return;
    }
    try {
      await appendNote('note', contextMenu.text, contextMenu.text);
      window.getSelection()?.removeAllRanges();
      setContextMenu(null);
    } catch (error) {
      console.error('Erreur lors de la création de la note :', error);
      alert('Impossible d’enregistrer la note.');
    }
  };

  const handleExplainSelection = async () => {
    if (!selectedReport || !contextMenu?.text) {
      return;
    }
    setDetailLoading(true);
    try {
      const result = await getReportDetail(selectedReport.id, contextMenu.text);
      await appendNote('detail', contextMenu.text, result.detail);
      window.getSelection()?.removeAllRanges();
      setContextMenu(null);
    } catch (error) {
      console.error('Erreur lors de la génération du détail :', error);
      alert('Impossible de générer un détail pour cette sélection.');
    } finally {
      setDetailLoading(false);
    }
  };

  const handleRemoveNote = async (noteId: number) => {
    try {
      await deleteNote(noteId);
      setNotes((current) => current.filter((note) => note.id !== noteId));
    } catch (error) {
      console.error('Erreur lors de la suppression de la note :', error);
      alert('Impossible de supprimer la note.');
    }
  };

  const handleMarkdownContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!selectedReport || !markdownRef.current) {
      return;
    }
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? '';
    const anchorNode = selection?.anchorNode;
    if (!text || !anchorNode || !markdownRef.current.contains(anchorNode)) {
      return;
    }
    event.preventDefault();
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      text,
    });
  };

  const handleAskChat = async () => {
    const question = chatInput.trim();
    if (!question) {
      return;
    }

    const pendingMessage: ChatMessage = {
      id: Date.now(),
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
      report_ids: selectedReport ? [selectedReport.id] : reports.slice(0, 3).map((report) => report.id),
    };
    setChatHistory((current) => [...current, pendingMessage]);
    setCurrentView('searches');
    setChatInput('');
    setChatLoading(true);

    try {
      await chatWithReports(
        question,
        selectedReport ? [selectedReport.id] : reports.slice(0, 3).map((report) => report.id),
      );
      await fetchChatHistory();
    } catch (error) {
      setChatHistory((current) => current.filter((message) => message.id !== pendingMessage.id));
      console.error('Erreur lors de la recherche chatbot :', error);
      alert('Impossible de lancer la recherche chatbot.');
    } finally {
      setChatLoading(false);
    }
  };

  const formatReportTimestamp = (value: string) =>
    new Date(value).toLocaleString('fr-FR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });

  const formatReportDay = (value: string) =>
    new Date(value).toLocaleDateString('fr-FR', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

  const groupedReports = reports.reduce<Record<string, Report[]>>((acc, report) => {
    const key = new Date(report.created_at).toISOString().slice(0, 10);
    acc[key] ??= [];
    acc[key].push(report);
    return acc;
  }, {});

  const groupEntries = Object.entries(groupedReports).sort(([a], [b]) => b.localeCompare(a));
  const selectedSummary = selectedReport ? summaryByReportId[selectedReport.id] : '';
  const selectedNotes = useMemo(
    () => (selectedReport ? notes.filter((note) => note.report_id === selectedReport.id) : []),
    [notes, selectedReport],
  );
  const linkedCount = reports.reduce(
    (count, report) => count + (report.content.match(/\[[^\]]+\]\(https?:\/\/[^\s)]+\)/g)?.length ?? 0),
    0,
  );
  const innovativeProjects = KNOWN_PROJECTS.filter((project) =>
    reports.some((report) => report.content.toLowerCase().includes(project.toLowerCase())),
  );
  const majorItemsCount = reports.reduce((count, report) => {
    const match = report.content.match(/## 1\. Nouveautés majeures([\s\S]*?)(## 2\.|$)/);
    return count + (match?.[1].match(/^- /gm)?.length ?? 0);
  }, 0);

  const renderReportsView = () => (
    <div className={`reports-view ${historyCollapsed ? 'collapsed' : ''}`}>
      {!historyCollapsed && (
        <aside className="reports-history-panel">
          <div className="reports-panel-header">
            <div>
              <h3>Historique des rapports</h3>
              <p className="panel-subtitle">Rapports regroupés par date de génération.</p>
            </div>
            <button
              className="icon-button"
              onClick={() => setHistoryCollapsed(true)}
              title="Masquer l’historique"
            >
              <ChevronLeft size={16} />
            </button>
          </div>
          {groupEntries.map(([day, dayReports]) => (
            <div key={day} className="report-group">
              <div className="report-group-title">{formatReportDay(dayReports[0].created_at)}</div>
              {dayReports.map((report) => (
                <div
                  key={report.id}
                  className={`report-item ${selectedReport?.id === report.id ? 'active' : ''}`}
                  onClick={() => setSelectedReport(report)}
                >
                  <div className="report-item-content">
                    <div className="report-item-main">
                      <FileText size={16} />
                      <div className="report-item-text">
                        <span className="report-item-title">Analyse technique</span>
                        <span className="report-item-meta">{formatReportTimestamp(report.created_at)}</span>
                      </div>
                    </div>
                    <div className="report-item-actions">
                      <button
                        className="icon-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenActionMenuId((current) => (current === report.id ? null : report.id));
                        }}
                      >
                        <MoreVertical size={16} />
                      </button>
                      {openActionMenuId === report.id && (
                        <div className="report-item-menu" onClick={(event) => event.stopPropagation()}>
                          <button onClick={() => handleDownload(report.id)}>
                            <Download size={16} />
                            Exporter en PDF
                          </button>
                          <button onClick={() => handleDeleteReport(report)} className="danger">
                            <Trash2 size={16} />
                            Supprimer le rapport
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ))}
          {reports.length === 0 && <p>Aucun rapport trouvé.</p>}
        </aside>
      )}

      <section className="report-content">
        <div className="report-content-toolbar">
          <button
            className="history-toggle-button"
            onClick={() => setHistoryCollapsed((current) => !current)}
          >
            {historyCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
            {historyCollapsed ? 'Afficher l’historique' : 'Masquer l’historique'}
          </button>
        </div>
        {selectedReport ? (
          <>
            <div className="actions">
              <h2>Analyse technique : {selectedReport.date}</h2>
              <div className="action-buttons">
                <button onClick={handleGenerateSummary} disabled={summaryLoading}>
                  <Sparkles size={18} />
                  {summaryLoading ? 'Génération du résumé...' : 'Résumé exécutif'}
                </button>
              </div>
            </div>
            {selectedSummary && (
              <section className="summary-card">
                <div className="summary-card-header">
                  <Sparkles size={18} />
                  <h3>Résumé exécutif</h3>
                </div>
                <div className="summary-card-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedSummary}</ReactMarkdown>
                </div>
              </section>
            )}
            <div className="markdown-body" ref={markdownRef} onContextMenu={handleMarkdownContextMenu}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedReport.content}</ReactMarkdown>
            </div>
            <section className="report-notes-section">
              <div className="report-notes-header">
                <NotebookPen size={18} />
                <h3>Notes du rapport</h3>
              </div>
              {selectedNotes.length > 0 ? (
                <div className="report-notes-list">
                  {selectedNotes.map((note) => (
                    <div key={note.id} className="note-card">
                      <div className="note-card-meta">
                        <span>{note.kind === 'detail' ? 'Détail' : 'Note'}</span>
                        <span>{formatReportTimestamp(note.created_at)}</span>
                      </div>
                      <p className="note-card-source">{note.source_text}</p>
                      <div className="note-card-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.content}</ReactMarkdown>
                      </div>
                      <button onClick={() => handleRemoveNote(note.id)} className="note-remove">
                        Supprimer
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="notes-empty">
                  Fais un clic droit sur une sélection dans le rapport pour l’ajouter aux notes ou demander un détail.
                </p>
              )}
            </section>
          </>
        ) : (
          <div className="empty-view">
            <Bot size={64} strokeWidth={1} style={{ marginBottom: '1rem' }} />
            <p>Sélectionne un rapport ou lance une nouvelle veille.</p>
          </div>
        )}
      </section>
    </div>
  );

  const renderDashboardView = () => (
    <div className="dashboard-view">
      <div className="dashboard-grid">
        <div className="dashboard-card">
          <span className="dashboard-card-label">Rapports</span>
          <strong>{reports.length}</strong>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">Éléments majeurs</span>
          <strong>{majorItemsCount}</strong>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">Articles référencés</span>
          <strong>{linkedCount}</strong>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">Notes enregistrées</span>
          <strong>{notes.length}</strong>
        </div>
      </div>
      <div className="dashboard-panels">
        <section className="dashboard-panel">
          <h3>Projets innovants mentionnés</h3>
          {innovativeProjects.length > 0 ? (
            <div className="tag-cloud">
              {innovativeProjects.map((project) => (
                <span key={project} className="project-tag">
                  {project}
                </span>
              ))}
            </div>
          ) : (
            <p className="notes-empty">Aucun projet suivi détecté pour l’instant.</p>
          )}
        </section>
        <section className="dashboard-panel">
          <h3>Dernier rapport</h3>
          {selectedReport ? (
            <>
              <p className="dashboard-latest-title">Analyse technique</p>
              <p className="dashboard-latest-meta">{formatReportTimestamp(selectedReport.created_at)}</p>
              <button onClick={() => setCurrentView('reports')} className="dashboard-link-button">
                Ouvrir le rapport
              </button>
            </>
          ) : (
            <p className="notes-empty">Aucun rapport disponible pour l’instant.</p>
          )}
        </section>
      </div>
    </div>
  );

  const renderNotesView = () => (
    <div className="notes-view">
      <h2>Notes</h2>
      {notes.length > 0 ? (
        <div className="report-notes-list">
          {notes.map((note) => (
            <div key={note.id} className="note-card">
              <div className="note-card-meta">
                <span>{note.kind === 'detail' ? 'Détail' : 'Note'}</span>
                <span>{formatReportTimestamp(note.created_at)}</span>
              </div>
              <button
                className="note-report-link"
                onClick={() => {
                  const report = reports.find((item) => item.id === note.report_id);
                  if (report) {
                    setSelectedReport(report);
                    setCurrentView('reports');
                  }
                }}
              >
                Rapport : {reports.find((item) => item.id === note.report_id)?.date ?? 'inconnu'}
              </button>
              <p className="note-card-source">{note.source_text}</p>
              <div className="note-card-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{note.content}</ReactMarkdown>
              </div>
              <button onClick={() => handleRemoveNote(note.id)} className="note-remove">
                Supprimer
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="notes-empty">Aucune note pour l’instant.</p>
      )}
    </div>
  );

  const renderSearchesView = () => (
    <div className="searches-view">
      <div className="searches-header">
        <h2>Recherches</h2>
        <p className="notes-empty">
          Pose des questions sur les rapports ou demande du contexte technique lié à une technologie.
        </p>
      </div>
      <div className="chat-panel">
        <div className="chat-history">
          {chatHistory.length > 0 ? (
            <>
              {chatHistory.map((message) => (
                <div key={message.id} className={`chat-message chat-message-${message.role}`}>
                  <div className="chat-message-role">{message.role === 'user' ? 'Vous' : 'Assistant'}</div>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                </div>
              ))}
              {chatLoading && (
                <div className="chat-message chat-message-assistant chat-message-loading">
                  <div className="chat-message-role">Assistant</div>
                  <div className="typing-indicator" aria-label="Réponse en cours de génération">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="notes-empty">Aucune recherche pour l’instant.</p>
          )}
        </div>
        <div className="chat-input-row">
          <textarea
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            placeholder="Pose une question sur un rapport, un outil, un provider ou une technologie mentionnée dans les rapports..."
          />
          <button onClick={handleAskChat} disabled={chatLoading}>
            {chatLoading ? 'Recherche en cours...' : 'Envoyer'}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <Bot size={28} color="#06b6d4" />
          <div>
            <strong>Veille IA Technique</strong>
            <span>Espace de veille opérationnelle</span>
          </div>
        </div>

        <nav className="topbar-menu">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={`topbar-link ${currentView === item.id ? 'active' : ''}`}
                onClick={() => setCurrentView(item.id)}
              >
                <Icon size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="topbar-actions">
          <button onClick={handleTrigger} disabled={loading} className="primary">
            <RefreshCw className={loading ? 'animate-spin' : ''} size={18} />
            {loading ? 'Analyse en cours...' : 'Lancer la veille'}
          </button>
        </div>
      </header>

      <main className="main-area">
        {currentView === 'dashboard' && renderDashboardView()}
        {currentView === 'reports' && renderReportsView()}
        {currentView === 'notes' && renderNotesView()}
        {currentView === 'searches' && renderSearchesView()}
      </main>

      {contextMenu && (
        <div
          className="selection-context-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(event) => event.stopPropagation()}
        >
          <button onClick={handleAddSelectionToNotes}>
            <NotebookPen size={16} />
            Ajouter aux notes
          </button>
          <button onClick={handleExplainSelection} disabled={detailLoading}>
            <Sparkles size={16} />
            {detailLoading ? 'Génération du détail...' : 'Détail'}
          </button>
        </div>
      )}
    </div>
  );
}

export default App;
