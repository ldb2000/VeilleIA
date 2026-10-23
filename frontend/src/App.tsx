import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Bookmark,
  BookmarkCheck,
  ChartColumn,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  MessageSquareShare,
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
  downloadReportPdf,
  downloadReportDocx,
  generateReportSummary,
  generateCodirNote,
  getChatMessages,
  getNews,
  getReportDefinition,
  getReportDetail,
  getReportNews,
  getReports,
  getReportSummary,
  getNotes,
  setNewsSaved,
  triggerReport,
} from './api';
import type { ChatMessage, NewsItem, Note, Report } from './api';
import './App.css';

type ContextMenuState = {
  x: number;
  y: number;
  text: string;
  variant: 'context' | 'toolbar';
} | null;

type MainView = 'dashboard' | 'reports' | 'news' | 'notes' | 'searches';

type ProjectSynthesisCacheEntry = {
  project: string;
  content: string;
  generatedAt: number;
};

type ReportSectionKind = 'tldr' | 'radar' | 'news' | 'generic';

type ReportSubsection = {
  title: string;
  body: string;
  bullets: string[];
};

type ReportSection = {
  id: string;
  title: string;
  kind: ReportSectionKind;
  body: string;
  bullets: string[];
  subsections: ReportSubsection[];
};

type ParsedReport = {
  preamble: string;
  sections: ReportSection[];
};

type NewsField = {
  label: string | null;
  value: string;
};

const PROJECT_SYNTHESIS_CACHE_KEY = 'veilleia.projectSynthesis.v1';
const PROJECT_SYNTHESIS_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const TEAMS_SHARE_URL =
  'https://teams.microsoft.com/l/chat/19:f5f9775520064c0a932a3a93567c0c6b@thread.v2/conversations?context=%7B%22contextType%22%3A%22chat%22%7D';

const NAV_ITEMS: Array<{ id: MainView; label: string; icon: typeof ChartColumn }> = [
  { id: 'dashboard', label: 'Tableau de bord', icon: ChartColumn },
  { id: 'reports', label: 'Rapports', icon: FileText },
  { id: 'news', label: 'News sauvegardées', icon: Bookmark },
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

const readProjectSynthesisCache = (): Record<string, ProjectSynthesisCacheEntry> => {
  try {
    const raw = window.localStorage.getItem(PROJECT_SYNTHESIS_CACHE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const writeProjectSynthesisCache = (cache: Record<string, ProjectSynthesisCacheEntry>) => {
  try {
    window.localStorage.setItem(PROJECT_SYNTHESIS_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // stockage indisponible : la synthèse reste valable pour la session
  }
};

// ===== Lecture structurée du rapport (TL;DR, Radar, Nouveautés, Signaux faibles) =====

const stripEmphasis = (text: string) => text.replace(/(\*\*|__|`)/g, '').trim();

const collectBullets = (lines: string[]) =>
  lines
    .map((line) => line.trim())
    .filter((line) => line.startsWith('- ') || line.startsWith('* '))
    .map((line) => line.slice(2).trim());

const classifySection = (title: string): ReportSectionKind => {
  const normalized = title.toLowerCase();
  if (/tl\s*;?\s*dr|essentiel/.test(normalized)) {
    return 'tldr';
  }
  if (normalized.includes('radar')) {
    return 'radar';
  }
  if (normalized.startsWith('nouveautés') || normalized.startsWith('nouveautes')) {
    return 'news';
  }
  return 'generic';
};

const parseReportContent = (content: string): ParsedReport | null => {
  const lines = content.split('\n');
  const preamble: string[] = [];
  const sections: ReportSection[] = [];
  let currentSection: (ReportSection & { lines: string[] }) | null = null;
  let currentSub: (ReportSubsection & { lines: string[] }) | null = null;

  const closeSub = () => {
    if (currentSection && currentSub) {
      currentSection.subsections.push({
        title: currentSub.title,
        body: currentSub.lines.join('\n').trim(),
        bullets: collectBullets(currentSub.lines),
      });
    }
    currentSub = null;
  };

  const closeSection = () => {
    closeSub();
    if (currentSection) {
      const { lines: sectionLines, ...section } = currentSection;
      sections.push({
        ...section,
        body: sectionLines.join('\n').trim(),
        bullets: collectBullets(sectionLines),
      });
    }
    currentSection = null;
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('## ') && !trimmed.startsWith('### ')) {
      closeSection();
      const title = stripEmphasis(trimmed.slice(3));
      currentSection = {
        id: `report-section-${sections.length}`,
        title,
        kind: classifySection(title),
        body: '',
        bullets: [],
        subsections: [],
        lines: [],
      };
      continue;
    }
    if (!currentSection) {
      preamble.push(line);
      continue;
    }
    if (trimmed.startsWith('### ')) {
      closeSub();
      currentSub = { title: stripEmphasis(trimmed.slice(4)), body: '', bullets: [], lines: [] };
      continue;
    }
    if (currentSub) {
      (currentSub as ReportSubsection & { lines: string[] }).lines.push(line);
    } else {
      (currentSection as ReportSection & { lines: string[] }).lines.push(line);
    }
  }
  closeSection();

  const hasKnownStructure = sections.some((section) => section.kind !== 'generic');
  if (!hasKnownStructure) {
    return null;
  }
  return { preamble: preamble.join('\n').trim(), sections };
};

const splitNewsField = (bullet: string): NewsField => {
  const match = bullet.match(/^\*{0,2}([^:*[\]()]{2,48}?)\*{0,2}\s*[:：](?!\/\/)\s*(.+)$/);
  if (!match) {
    return { label: null, value: bullet };
  }
  return { label: match[1].trim(), value: match[2].trim() };
};

const isLabel = (label: string | null, prefix: string) =>
  Boolean(label && label.toLowerCase().startsWith(prefix));

const radarTone = (title: string) => {
  const normalized = title.toLowerCase();
  if (normalized.includes('tester')) {
    return 'test';
  }
  if (normalized.includes('surveiller')) {
    return 'watch';
  }
  if (normalized.includes('ignorer')) {
    return 'ignore';
  }
  return 'watch';
};

const maturityTone = (maturity: string) => {
  const normalized = maturity.toLowerCase();
  if (/\bga\b|production/.test(normalized)) {
    return 'green';
  }
  if (/bêta|beta/.test(normalized)) {
    return 'orange';
  }
  return 'blue';
};

const countSources = (content: string) =>
  content.match(/\[[^\]]+\]\(https?:\/\/[^\s)]+\)/g)?.length ?? 0;

function App() {
  const [reports, setReports] = useState<Report[]>([]);
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);
  const [currentView, setCurrentView] = useState<MainView>('dashboard');
  const [loading, setLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [definitionLoading, setDefinitionLoading] = useState(false);
  const [codirLoading, setCodirLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [historyFilter, setHistoryFilter] = useState('');
  const [summaryByReportId, setSummaryByReportId] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<Note[]>([]);
  const [reportNews, setReportNews] = useState<NewsItem[]>([]);
  const [savedNews, setSavedNews] = useState<NewsItem[]>([]);
  const [newsSaving, setNewsSaving] = useState<number | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [projectSynthesis, setProjectSynthesis] = useState<{ project: string; content: string } | null>(null);
  const [projectSynthesisLoading, setProjectSynthesisLoading] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
  const [openActionMenuId, setOpenActionMenuId] = useState<number | null>(null);
  const [summaryReadIds, setSummaryReadIds] = useState<Set<number>>(new Set());
  const [summaryExpanded, setSummaryExpanded] = useState(true);
  const markdownRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchReports();
    fetchNotes();
    fetchChatHistory();
    fetchSavedNews();
  }, []);

  useEffect(() => {
    if (!selectedReport) {
      setReportNews([]);
      return;
    }
    loadSummary(selectedReport.id);
    loadReportNews(selectedReport);
    setSummaryExpanded(!summaryReadIds.has(selectedReport.id));
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

  const fetchSavedNews = async () => {
    try {
      const data = await getNews({ saved: true });
      setSavedNews(data);
    } catch (error) {
      console.error('Erreur lors du chargement des news sauvegardées :', error);
    }
  };

  const loadReportNews = async (report: Report) => {
    if (report.report_type !== 'technical_watch') {
      setReportNews([]);
      return;
    }
    try {
      const data = await getReportNews(report.id);
      setReportNews(data);
    } catch (error) {
      setReportNews([]);
      console.error('Erreur lors du chargement des news du rapport :', error);
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
      setSummaryReadIds((current) => new Set(current).add(reportId));
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

  const handleDownload = async (id: number) => {
    try {
      const pdf = await downloadReportPdf(id);
      const url = URL.createObjectURL(pdf);
      const link = document.createElement('a');
      link.href = url;
      link.download = `ai_watch_${selectedReport?.date ?? id}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Erreur lors de l’export PDF :', error);
      alert('Impossible d’exporter le PDF.');
    }
  };

  const handleDownloadDocx = async (report: Report) => {
    try {
      const docx = await downloadReportDocx(report.id);
      const url = URL.createObjectURL(docx);
      const link = document.createElement('a');
      link.href = url;
      link.download = `note_codir_veille_ia_${report.date}.docx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Erreur lors de l’export Word :', error);
      alert('Impossible d’exporter la note CODIR.');
    }
  };

  const handleShareTeams = async (report: Report) => {
    if (report.report_type === 'codir_note') {
      await handleDownloadDocx(report);
    } else {
      await handleDownload(report.id);
    }
    window.open(TEAMS_SHARE_URL, '_blank', 'noopener,noreferrer');
  };

  const handleDeleteReport = async (report: Report) => {
    const confirmed = window.confirm(
      'Supprimer ce rapport ? Les news que vous avez sauvegardées sont conservées.',
    );
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

  const handleToggleSaveNews = async (item: NewsItem) => {
    setNewsSaving(item.id);
    try {
      const updated = await setNewsSaved(item.id, !item.saved);
      setReportNews((current) => current.map((news) => (news.id === updated.id ? updated : news)));
      setSavedNews((current) => {
        const others = current.filter((news) => news.id !== updated.id);
        return updated.saved ? [updated, ...others] : others;
      });
    } catch (error) {
      console.error('Erreur lors de la sauvegarde de la news :', error);
      alert('Impossible de sauvegarder cette news.');
    } finally {
      setNewsSaving(null);
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
      setSummaryExpanded(true);
    } catch (error) {
      console.error('Erreur lors de la génération du résumé :', error);
      alert('Impossible de générer le résumé exécutif.');
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleGenerateCodirNote = async () => {
    if (!selectedReport || selectedReport.report_type === 'codir_note') {
      return;
    }
    setCodirLoading(true);
    try {
      const newReport = await generateCodirNote(selectedReport.id);
      setReports((current) => [newReport, ...current]);
      setSelectedReport(newReport);
      setCurrentView('reports');
    } catch (error) {
      console.error('Erreur lors de la génération de la note CODIR :', error);
      alert('Impossible de générer la note CODIR.');
    } finally {
      setCodirLoading(false);
    }
  };

  const appendNote = async (kind: 'note' | 'detail' | 'definition', sourceText: string, content: string) => {
    if (!selectedReport) {
      return;
    }
    const newNote = await createNote(selectedReport.id, {
      kind,
      source_text: sourceText,
      content,
    });
    setNotes((current) =>
      current.some((note) => note.id === newNote.id) ? current : [newNote, ...current],
    );
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

  const handleDefineSelection = async () => {
    if (!selectedReport || !contextMenu?.text) {
      return;
    }
    setDefinitionLoading(true);
    try {
      const result = await getReportDefinition(selectedReport.id, contextMenu.text);
      await appendNote('definition', contextMenu.text, result.definition);
      window.getSelection()?.removeAllRanges();
      setContextMenu(null);
    } catch (error) {
      console.error('Erreur lors de la génération de la définition :', error);
      alert('Impossible de générer une définition pour cette sélection.');
    } finally {
      setDefinitionLoading(false);
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

  const readSelectionInReport = () => {
    if (!selectedReport || !markdownRef.current) {
      return null;
    }
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? '';
    const anchorNode = selection?.anchorNode;
    if (!selection || !text || !anchorNode || !markdownRef.current.contains(anchorNode)) {
      return null;
    }
    return { selection, text };
  };

  const handleMarkdownContextMenu = (event: React.MouseEvent<HTMLDivElement>) => {
    const current = readSelectionInReport();
    if (!current) {
      return;
    }
    event.preventDefault();
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      text: current.text,
      variant: 'context',
    });
  };

  const handleMarkdownMouseUp = (event: React.MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    const current = readSelectionInReport();
    if (!current || current.selection.rangeCount === 0) {
      return;
    }
    const rect = current.selection.getRangeAt(0).getBoundingClientRect();
    setContextMenu({
      x: rect.left + rect.width / 2,
      y: Math.max(rect.top - 10, 12),
      text: current.text,
      variant: 'toolbar',
    });
  };

  const handleMarkdownClick = (event: React.MouseEvent<HTMLDivElement>) => {
    // Garde la barre d'outils ouverte après une sélection à la souris.
    if (window.getSelection()?.toString().trim()) {
      event.stopPropagation();
    }
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

  const handleProjectSynthesis = async (project: string) => {
    const cacheKey = project.toLowerCase();
    const cache = readProjectSynthesisCache();
    const cached = cache[cacheKey];
    if (cached && Date.now() - cached.generatedAt < PROJECT_SYNTHESIS_MAX_AGE_MS) {
      setProjectSynthesis(cached);
      return;
    }

    const reportIds = reports
      .filter((report) => report.content.toLowerCase().includes(project.toLowerCase()))
      .slice(0, 3)
      .map((report) => report.id);

    if (reportIds.length === 0) {
      return;
    }

    setProjectSynthesisLoading(project);
    try {
      const result = await chatWithReports(
        `Fais une synthèse courte sur ${project} à partir des rapports fournis. Réponds en 4 points maximum : nouveauté, intérêt pour APRIL, risque ou limite, action recommandée.`,
        reportIds,
      );
      const nextSynthesis = { project, content: result.answer, generatedAt: Date.now() };
      setProjectSynthesis(nextSynthesis);
      writeProjectSynthesisCache({
        ...cache,
        [cacheKey]: nextSynthesis,
      });
      await fetchChatHistory();
    } catch (error) {
      console.error('Erreur lors de la synthèse projet :', error);
      alert('Impossible de générer la synthèse du projet.');
    } finally {
      setProjectSynthesisLoading(null);
    }
  };

  const openReport = (reportId: number) => {
    const report = reports.find((item) => item.id === reportId);
    if (report) {
      setSelectedReport(report);
      setCurrentView('reports');
    }
  };

  const scrollToSection = (sectionId: string) => {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const formatReportTimestamp = (value: string) =>
    new Date(value).toLocaleString('fr-FR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });

  const formatReportTime = (value: string) =>
    new Date(value).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

  const formatReportDay = (value: string) =>
    new Date(value).toLocaleDateString('fr-FR', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

  const getReportTitle = (report: Report) =>
    report.report_type === 'codir_note' ? 'Note CODIR' : 'Analyse technique';

  const getNoteKindLabel = (kind: string) => {
    if (kind === 'detail') {
      return 'Détail';
    }
    if (kind === 'definition') {
      return 'Définition';
    }
    return 'Note';
  };

  const normalizedFilter = historyFilter.trim().toLowerCase();
  const filteredReports = normalizedFilter
    ? reports.filter(
        (report) =>
          report.content.toLowerCase().includes(normalizedFilter) ||
          report.date.includes(normalizedFilter) ||
          getReportTitle(report).toLowerCase().includes(normalizedFilter),
      )
    : reports;

  const groupedReports = filteredReports.reduce<Record<string, Report[]>>((acc, report) => {
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
  const parsedReport = useMemo(
    () =>
      selectedReport && selectedReport.report_type !== 'codir_note'
        ? parseReportContent(selectedReport.content)
        : null,
    [selectedReport],
  );
  const linkedCount = reports.reduce((count, report) => count + countSources(report.content), 0);
  const innovativeProjects = KNOWN_PROJECTS.filter((project) =>
    reports.some((report) => report.content.toLowerCase().includes(project.toLowerCase())),
  );
  const majorItemsCount = reports.reduce((count, report) => {
    const parsed = report.report_type === 'technical_watch' ? parseReportContent(report.content) : null;
    const newsSection = parsed?.sections.find((section) => section.kind === 'news');
    if (newsSection) {
      return count + newsSection.subsections.length;
    }
    const legacy = report.content.match(/## 1\. Nouveautés majeures([\s\S]*?)(## 2\.|$)/);
    return count + (legacy?.[1].match(/^- /gm)?.length ?? 0);
  }, 0);

  const renderMarkdown = (content: string) => (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
  );

  const renderPetalList = (items: string[], tone: 'blue' | 'green' | 'orange' | 'muted' = 'blue') => (
    <ul className={`petal-list petal-${tone}`}>
      {items.map((item, index) => (
        <li key={index}>{renderMarkdown(item)}</li>
      ))}
    </ul>
  );

  const renderNewsCard = (subsection: ReportSubsection, index: number) => {
    const fields = subsection.bullets.map(splitNewsField);
    const maturityField = fields.find((field) => isLabel(field.label, 'maturit'));
    const actionField = fields.find((field) => isLabel(field.label, 'action'));
    const otherFields = fields.filter((field) => field !== maturityField && field !== actionField);
    const labelledFields = otherFields.filter((field) => field.label);
    const plainFields = otherFields.filter((field) => !field.label);
    const newsItem =
      reportNews.find((item) => item.position === index && item.title === subsection.title) ??
      reportNews.find((item) => item.title === subsection.title) ??
      null;
    const maturity = newsItem?.maturity ?? maturityField?.value ?? null;
    const hasStructuredFields = subsection.bullets.length > 0;

    return (
      <article key={`${subsection.title}-${index}`} className="news-card">
        <header className="news-card-header">
          <h3>{subsection.title}</h3>
          <div className="news-card-tools">
            {maturity && (
              <span className={`badge badge-${maturityTone(maturity)}`}>{stripEmphasis(maturity)}</span>
            )}
            {newsItem && (
              <button
                type="button"
                className={`save-news-button ${newsItem.saved ? 'saved' : ''}`}
                onClick={() => handleToggleSaveNews(newsItem)}
                disabled={newsSaving === newsItem.id}
                aria-pressed={newsItem.saved}
              >
                {newsItem.saved ? <BookmarkCheck size={16} /> : <Bookmark size={16} />}
                {newsItem.saved ? 'Sauvegardée' : 'Sauvegarder'}
              </button>
            )}
          </div>
        </header>
        {hasStructuredFields ? (
          <>
            {labelledFields.length > 0 && (
              <dl className="news-fields">
                {labelledFields.map((field, fieldIndex) => (
                  <div key={fieldIndex} className="news-field">
                    <dt>{field.label}</dt>
                    <dd>{renderMarkdown(field.value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            {plainFields.length > 0 && renderPetalList(plainFields.map((field) => field.value), 'blue')}
          </>
        ) : (
          <div className="news-card-body">{renderMarkdown(subsection.body)}</div>
        )}
        {actionField && (
          <div className="callout callout-green">
            <strong>Action recommandée</strong>
            {renderMarkdown(actionField.value)}
          </div>
        )}
      </article>
    );
  };

  const renderStructuredSection = (section: ReportSection) => {
    if (section.kind === 'tldr') {
      return (
        <section key={section.id} id={section.id} className="report-block tldr-card">
          <h2 className="section-header">L’essentiel en 30 secondes</h2>
          {section.bullets.length > 0 ? renderPetalList(section.bullets) : renderMarkdown(section.body)}
        </section>
      );
    }

    if (section.kind === 'radar') {
      return (
        <section key={section.id} id={section.id} className="report-block">
          <h2 className="section-header">{section.title}</h2>
          {section.subsections.length > 0 ? (
            <div className="radar-grid">
              {section.subsections.map((column) => {
                const tone = radarTone(column.title);
                return (
                  <div key={column.title} className={`radar-column radar-${tone}`}>
                    <div className="radar-column-header">
                      <h3>{column.title}</h3>
                      <span className="radar-count">{column.bullets.length}</span>
                    </div>
                    {column.bullets.length > 0 ? (
                      renderPetalList(
                        column.bullets,
                        tone === 'test' ? 'green' : tone === 'ignore' ? 'muted' : 'orange',
                      )
                    ) : (
                      <p className="muted-text">Rien à signaler.</p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="markdown-body">{renderMarkdown(section.body)}</div>
          )}
        </section>
      );
    }

    if (section.kind === 'news') {
      return (
        <section key={section.id} id={section.id} className="report-block">
          <h2 className="section-header">{section.title}</h2>
          {section.body && <div className="markdown-body">{renderMarkdown(section.body)}</div>}
          <div className="news-list">
            {section.subsections.map((subsection, index) => renderNewsCard(subsection, index))}
          </div>
        </section>
      );
    }

    return (
      <section key={section.id} id={section.id} className="report-block">
        <h2 className="section-header">{section.title}</h2>
        <div className="surface-card markdown-body">
          {section.body && renderMarkdown(section.body)}
          {section.subsections.map((subsection) => (
            <div key={subsection.title} className="generic-subsection">
              <h3>{subsection.title}</h3>
              {renderMarkdown(subsection.body)}
            </div>
          ))}
        </div>
      </section>
    );
  };

  const renderNoteCard = (note: Note, options: { compact?: boolean; showReport?: boolean } = {}) => (
    <article key={note.id} className={`note-card ${options.compact ? 'compact' : ''}`}>
      <div className="note-card-meta">
        <span className={`badge badge-${note.kind === 'definition' ? 'magenta' : note.kind === 'detail' ? 'cyan' : 'blue'}`}>
          {getNoteKindLabel(note.kind)}
        </span>
        <span>{formatReportTimestamp(note.created_at)}</span>
      </div>
      {options.showReport && (
        <button type="button" className="link-button" onClick={() => openReport(note.report_id)}>
          Rapport : {reports.find((item) => item.id === note.report_id)?.date ?? 'inconnu'}
        </button>
      )}
      {note.source_text !== note.content && <p className="note-card-source">« {note.source_text} »</p>}
      <div className="note-card-content">{renderMarkdown(note.content)}</div>
      <button type="button" onClick={() => handleRemoveNote(note.id)} className="note-remove">
        Supprimer
      </button>
    </article>
  );

  const renderReportsView = () => {
    const tocSections = parsedReport?.sections ?? [];
    const sourcesCount = selectedReport ? countSources(selectedReport.content) : 0;
    const savedInReport = reportNews.filter((item) => item.saved).length;

    return (
      <div className={`reports-view ${historyCollapsed ? 'collapsed' : ''}`}>
        {!historyCollapsed && (
          <aside className="reports-history-panel" aria-label="Historique des rapports">
            <div className="reports-panel-header">
              <h2>Historique</h2>
              <button
                type="button"
                className="icon-button"
                onClick={() => setHistoryCollapsed(true)}
                title="Masquer l’historique"
                aria-label="Masquer l’historique"
              >
                <ChevronLeft size={16} />
              </button>
            </div>
            <label className="history-filter">
              <span>Filtrer les rapports</span>
              <input
                type="search"
                value={historyFilter}
                onChange={(event) => setHistoryFilter(event.target.value)}
                placeholder="Mot-clé, outil, date…"
              />
            </label>
            {groupEntries.map(([day, dayReports]) => (
              <div key={day} className="report-group">
                <div className="report-group-title">{formatReportDay(dayReports[0].created_at)}</div>
                {dayReports.map((report) => (
                  <div
                    key={report.id}
                    className={`report-item ${selectedReport?.id === report.id ? 'active' : ''} ${
                      openActionMenuId === report.id ? 'menu-open' : ''
                    }`}
                    onClick={() => setSelectedReport(report)}
                  >
                    <div className="report-item-content">
                      <div className="report-item-text">
                        <span className="report-item-title">{getReportTitle(report)}</span>
                        <span className="report-item-meta">{formatReportTime(report.created_at)}</span>
                      </div>
                      <div className="report-item-actions">
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Actions du rapport"
                          onClick={(event) => {
                            event.stopPropagation();
                            setOpenActionMenuId((current) => (current === report.id ? null : report.id));
                          }}
                        >
                          <MoreVertical size={16} />
                        </button>
                        {openActionMenuId === report.id && (
                          <div className="report-item-menu" onClick={(event) => event.stopPropagation()}>
                            <button type="button" onClick={() => handleDownload(report.id)}>
                              <Download size={16} />
                              Exporter en PDF
                            </button>
                            {report.report_type === 'codir_note' && (
                              <button type="button" onClick={() => handleDownloadDocx(report)}>
                                <Download size={16} />
                                Exporter en Word
                              </button>
                            )}
                            <button type="button" onClick={() => handleShareTeams(report)}>
                              <MessageSquareShare size={16} />
                              Partager dans Teams
                            </button>
                            <button type="button" onClick={() => handleDeleteReport(report)} className="danger">
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
            {filteredReports.length === 0 && (
              <p className="muted-text">{reports.length === 0 ? 'Aucun rapport pour l’instant.' : 'Aucun rapport ne correspond.'}</p>
            )}
          </aside>
        )}

        <section className="report-content">
          {historyCollapsed && (
            <button
              type="button"
              className="history-toggle-button"
              onClick={() => setHistoryCollapsed(false)}
            >
              <ChevronRight size={16} />
              Afficher l’historique
            </button>
          )}
          {selectedReport ? (
            <>
              <header className="report-hero">
                <div className="kicker">
                  {getReportTitle(selectedReport)} · {formatReportDay(selectedReport.created_at)}
                </div>
                <h1>{selectedReport.report_type === 'codir_note' ? 'Note pour le CODIR' : 'Veille IA du jour'}</h1>
                <div className="badge-row">
                  {reportNews.length > 0 && (
                    <span className="badge badge-green solid">
                      {reportNews.length} nouveauté{reportNews.length > 1 ? 's' : ''}
                    </span>
                  )}
                  {sourcesCount > 0 && (
                    <span className="badge badge-blue">
                      {sourcesCount} source{sourcesCount > 1 ? 's' : ''}
                    </span>
                  )}
                  {savedInReport > 0 && (
                    <span className="badge badge-orange">
                      {savedInReport} sauvegardée{savedInReport > 1 ? 's' : ''}
                    </span>
                  )}
                  {selectedSummary && <span className="badge badge-cyan">Résumé exécutif prêt</span>}
                </div>
                <div className="action-buttons">
                  {selectedReport.report_type !== 'codir_note' ? (
                    <>
                      <button type="button" className="btn btn-primary" onClick={handleGenerateCodirNote} disabled={codirLoading}>
                        <FileText size={16} />
                        {codirLoading ? 'Génération CODIR…' : 'Générer la note CODIR'}
                      </button>
                      <button type="button" className="btn btn-secondary" onClick={handleGenerateSummary} disabled={summaryLoading}>
                        <Sparkles size={16} />
                        {summaryLoading ? 'Génération du résumé…' : 'Résumé exécutif'}
                      </button>
                    </>
                  ) : (
                    <button type="button" className="btn btn-primary" onClick={() => handleDownloadDocx(selectedReport)}>
                      <Download size={16} />
                      Exporter en Word
                    </button>
                  )}
                  <button type="button" className="btn btn-ghost" onClick={() => handleDownload(selectedReport.id)}>
                    <Download size={16} />
                    Exporter en PDF
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => handleShareTeams(selectedReport)}>
                    <MessageSquareShare size={16} />
                    Partager dans Teams
                  </button>
                </div>
              </header>

              {selectedSummary && (
                <section className="summary-card">
                  <button
                    type="button"
                    className="summary-card-toggle"
                    onClick={() => setSummaryExpanded((current) => !current)}
                    aria-expanded={summaryExpanded}
                  >
                    <Sparkles size={18} />
                    <span>Résumé exécutif</span>
                    <ChevronDown size={16} className={`summary-chevron ${summaryExpanded ? '' : 'collapsed'}`} />
                  </button>
                  {summaryExpanded && <div className="summary-card-body markdown-body">{renderMarkdown(selectedSummary)}</div>}
                </section>
              )}

              <div
                className="report-reading"
                ref={markdownRef}
                onContextMenu={handleMarkdownContextMenu}
                onMouseUp={handleMarkdownMouseUp}
                onClick={handleMarkdownClick}
              >
                {parsedReport ? (
                  <>
                    {parsedReport.preamble && (
                      <div className="surface-card markdown-body">{renderMarkdown(parsedReport.preamble)}</div>
                    )}
                    {parsedReport.sections.map(renderStructuredSection)}
                  </>
                ) : (
                  <div className="surface-card markdown-body">{renderMarkdown(selectedReport.content)}</div>
                )}
              </div>
            </>
          ) : (
            <div className="empty-view">
              <p>Sélectionnez un rapport ou lancez une nouvelle veille.</p>
            </div>
          )}
        </section>

        {selectedReport && (
          <aside className="report-side-rail" aria-label="Sommaire et notes">
            {tocSections.length > 0 && (
              <nav className="toc-card" aria-label="Sur cette page">
                <div className="eyebrow">Sur cette page</div>
                {tocSections.map((section) => (
                  <button
                    key={section.id}
                    type="button"
                    className="toc-link"
                    onClick={() => scrollToSection(section.id)}
                  >
                    {section.kind === 'tldr' ? 'L’essentiel' : section.title}
                  </button>
                ))}
              </nav>
            )}
            <section className="rail-notes">
              <div className="rail-notes-header">
                <h2>Notes du rapport</h2>
                <span>{selectedNotes.length}</span>
              </div>
              {selectedNotes.map((note) => renderNoteCard(note, { compact: true }))}
              <p className="muted-text">
                Sélectionnez un passage du rapport pour l’ajouter aux notes, l’approfondir ou le définir.
              </p>
            </section>
          </aside>
        )}
      </div>
    );
  };

  const renderNewsView = () => (
    <div className="news-view">
      <div className="view-header">
        <h1>News sauvegardées</h1>
        <p className="muted-text">
          Les nouveautés que vous avez sauvegardées depuis les rapports. Elles sont conservées même si le rapport est supprimé.
        </p>
      </div>
      {savedNews.length > 0 ? (
        <div className="news-list">
          {savedNews.map((item) => {
            const reportExists = reports.some((report) => report.id === item.report_id);
            return (
              <article key={item.id} className="news-card">
                <header className="news-card-header">
                  <h3>{item.title}</h3>
                  <div className="news-card-tools">
                    {item.maturity && (
                      <span className={`badge badge-${maturityTone(item.maturity)}`}>{item.maturity}</span>
                    )}
                    <button
                      type="button"
                      className="save-news-button saved"
                      onClick={() => handleToggleSaveNews(item)}
                      disabled={newsSaving === item.id}
                    >
                      <BookmarkCheck size={16} />
                      Retirer
                    </button>
                  </div>
                </header>
                <div className="news-card-meta">
                  {reportExists ? (
                    <button type="button" className="link-button" onClick={() => openReport(item.report_id)}>
                      Analyse du {item.report_date ?? 'rapport'}
                    </button>
                  ) : (
                    <span>Analyse du {item.report_date ?? '—'} (rapport supprimé)</span>
                  )}
                  {item.saved_at && <span>Sauvegardée le {formatReportTimestamp(item.saved_at)}</span>}
                </div>
                <div className="news-card-body markdown-body">{renderMarkdown(item.content)}</div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="surface-card">
          <p className="muted-text">
            Aucune news sauvegardée. Dans un rapport, utilisez le bouton « Sauvegarder » d’une nouveauté pour la retrouver ici.
          </p>
        </div>
      )}
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
          <span className="dashboard-card-label">Nouveautés détaillées</span>
          <strong>{majorItemsCount}</strong>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">Sources référencées</span>
          <strong>{linkedCount}</strong>
        </div>
        <div className="dashboard-card">
          <span className="dashboard-card-label">News sauvegardées</span>
          <strong>{savedNews.length}</strong>
        </div>
      </div>
      <div className="dashboard-panels">
        <section className="dashboard-panel">
          <h2 className="section-header">Projets suivis</h2>
          {innovativeProjects.length > 0 ? (
            <>
              <div className="tag-cloud">
                {innovativeProjects.map((project) => (
                  <button
                    type="button"
                    key={project}
                    className={`project-tag ${projectSynthesis?.project === project ? 'active' : ''}`}
                    onClick={() => handleProjectSynthesis(project)}
                    disabled={projectSynthesisLoading !== null}
                    aria-pressed={projectSynthesis?.project === project}
                  >
                    {projectSynthesisLoading === project ? 'Synthèse…' : project}
                  </button>
                ))}
              </div>
              {projectSynthesis && (
                <div className="project-synthesis">
                  <div className="project-synthesis-header">
                    <span>Synthèse</span>
                    <strong>{projectSynthesis.project}</strong>
                  </div>
                  {renderMarkdown(projectSynthesis.content)}
                </div>
              )}
            </>
          ) : (
            <p className="muted-text">Aucun projet suivi détecté pour l’instant.</p>
          )}
        </section>
        <section className="dashboard-panel">
          <h2 className="section-header">Dernier rapport</h2>
          {selectedReport ? (
            <>
              <p className="dashboard-latest-title">{getReportTitle(selectedReport)}</p>
              <p className="dashboard-latest-meta">{formatReportTimestamp(selectedReport.created_at)}</p>
              <button type="button" onClick={() => setCurrentView('reports')} className="btn btn-secondary">
                Ouvrir le rapport
              </button>
            </>
          ) : (
            <p className="muted-text">Aucun rapport disponible pour l’instant.</p>
          )}
        </section>
      </div>
    </div>
  );

  const renderNotesView = () => (
    <div className="notes-view">
      <div className="view-header">
        <h1>Notes</h1>
      </div>
      {notes.length > 0 ? (
        <div className="report-notes-list">{notes.map((note) => renderNoteCard(note, { showReport: true }))}</div>
      ) : (
        <p className="muted-text">Aucune note pour l’instant.</p>
      )}
    </div>
  );

  const renderSearchesView = () => (
    <div className="searches-view">
      <div className="view-header">
        <h1>Recherches</h1>
        <p className="muted-text">
          Posez des questions sur les rapports ou demandez du contexte technique sur une technologie.
        </p>
      </div>
      <div className="chat-panel">
        <div className="chat-history">
          {chatHistory.length > 0 ? (
            <>
              {chatHistory.map((message) => (
                <div key={message.id} className={`chat-message chat-message-${message.role}`}>
                  <div className="chat-message-role">{message.role === 'user' ? 'Vous' : 'Assistant'}</div>
                  {renderMarkdown(message.content)}
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
            <p className="muted-text">Aucune recherche pour l’instant.</p>
          )}
        </div>
        <div className="chat-input-row">
          <label htmlFor="chat-question" className="visually-hidden">Votre question</label>
          <textarea
            id="chat-question"
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            placeholder="Posez une question sur un rapport, un outil, un provider ou une technologie…"
          />
          <button type="button" className="btn btn-primary" onClick={handleAskChat} disabled={chatLoading}>
            {chatLoading ? 'Recherche en cours…' : 'Envoyer'}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="app-frame">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="topbar-brand">
            <span className="brand-leaf" aria-hidden="true">
              <span className="brand-leaf-quarter" />
              <span className="brand-leaf-petal" />
            </span>
            <div>
              <strong>Veille IA</strong>
              <span>STTI · APRIL</span>
            </div>
          </div>

          <nav className="topbar-menu" aria-label="Navigation principale">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  type="button"
                  key={item.id}
                  className={`topbar-link ${currentView === item.id ? 'active' : ''}`}
                  onClick={() => setCurrentView(item.id)}
                  aria-current={currentView === item.id ? 'page' : undefined}
                >
                  <Icon size={16} />
                  {item.label}
                  {item.id === 'news' && savedNews.length > 0 && (
                    <span className="nav-count">{savedNews.length}</span>
                  )}
                </button>
              );
            })}
          </nav>

          <div className="topbar-actions">
            <button type="button" onClick={handleTrigger} disabled={loading} className="btn btn-primary">
              <RefreshCw className={loading ? 'animate-spin' : ''} size={16} />
              {loading ? 'Analyse en cours…' : 'Lancer la veille'}
            </button>
          </div>
        </div>
        <div className="accent-bar" />
      </header>

      <main className="app-shell">
        {currentView === 'dashboard' && renderDashboardView()}
        {currentView === 'reports' && renderReportsView()}
        {currentView === 'news' && renderNewsView()}
        {currentView === 'notes' && renderNotesView()}
        {currentView === 'searches' && renderSearchesView()}
      </main>

      {contextMenu && (
        <div
          className={`selection-menu selection-menu-${contextMenu.variant}`}
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(event) => event.stopPropagation()}
          onMouseUp={(event) => event.stopPropagation()}
          role="toolbar"
          aria-label="Actions sur la sélection"
        >
          <button type="button" onClick={handleAddSelectionToNotes}>
            <NotebookPen size={15} />
            Ajouter aux notes
          </button>
          <button type="button" onClick={handleExplainSelection} disabled={detailLoading}>
            <Sparkles size={15} />
            {detailLoading ? 'Génération…' : 'Approfondir'}
          </button>
          <button type="button" onClick={handleDefineSelection} disabled={definitionLoading}>
            <FileText size={15} />
            {definitionLoading ? 'Génération…' : 'Définir'}
          </button>
        </div>
      )}
    </div>
  );
}

export default App;
