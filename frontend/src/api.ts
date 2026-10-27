import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const API_TOKEN = import.meta.env.VITE_API_TOKEN;

if (API_TOKEN) {
  axios.defaults.headers.common['Authorization'] = `Bearer ${API_TOKEN}`;
}

export interface Report {
  id: number;
  date: string;
  report_type: string;
  content: string;
  created_at: string;
  newsletter_sent_at?: string | null;
}

export interface ReportSummary {
  report_id: number;
  summary: string;
  updated_at: string;
}

export interface ReportDetail {
  detail: string;
}

export interface ReportDefinition {
  definition: string;
}

export interface ChatAnswer {
  answer: string;
}

export interface Note {
  id: number;
  report_id: number;
  kind: string;
  source_text: string;
  content: string;
  created_at: string;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  report_ids?: number[] | null;
  created_at: string;
}

export const getReports = async (): Promise<Report[]> => {
  const response = await axios.get(`${API_URL}/reports`);
  return response.data;
};

export const getReport = async (id: number): Promise<Report> => {
  const response = await axios.get(`${API_URL}/reports/${id}`);
  return response.data;
};

export interface Job {
  id: string;
  kind: string;
  status: 'running' | 'done' | 'error';
  report_id: number | null;
  error: string | null;
  started_at: string;
}

const JOB_POLL_INTERVAL_MS = 3000;

// Les générations longues tournent en tâche de fond côté backend (le proxy Cloudflare coupe
// au-delà de 125 s) : on interroge la tâche jusqu'à la fin puis on charge le rapport créé.
const waitForJobReport = async (job: Job): Promise<Report> => {
  let current = job;
  while (current.status === 'running') {
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    current = (await axios.get<Job>(`${API_URL}/jobs/${current.id}`)).data;
  }
  if (current.status === 'error' || current.report_id === null) {
    throw new Error(current.error ?? 'La génération a échoué.');
  }
  return getReport(current.report_id);
};

export const triggerReport = async (): Promise<Report> => {
  const response = await axios.post<Job>(`${API_URL}/reports/trigger`);
  return waitForJobReport(response.data);
};

// Veille Microsoft Copilot (7 derniers jours) : rapport de type copilot_watch.
export const triggerCopilotReport = async (): Promise<Report> => {
  const response = await axios.post<Job>(`${API_URL}/reports/copilot/trigger`);
  return waitForJobReport(response.data);
};

export const generateCodirNote = async (id: number): Promise<Report> => {
  const response = await axios.post<Job>(`${API_URL}/reports/${id}/codir`);
  return waitForJobReport(response.data);
};

export const deleteReport = async (id: number): Promise<void> => {
  await axios.delete(`${API_URL}/reports/${id}`);
};

export const getReportSummary = async (id: number): Promise<ReportSummary> => {
  const response = await axios.get(`${API_URL}/reports/${id}/summary`);
  return response.data;
};

export const generateReportSummary = async (id: number): Promise<ReportSummary> => {
  const response = await axios.post(`${API_URL}/reports/${id}/summary`);
  return response.data;
};

export const getReportDetail = async (id: number, selectedText: string): Promise<ReportDetail> => {
  const response = await axios.post(`${API_URL}/reports/${id}/detail`, null, {
    params: { selected_text: selectedText },
  });
  return response.data;
};

export const getReportDefinition = async (id: number, selectedText: string): Promise<ReportDefinition> => {
  const response = await axios.post(`${API_URL}/reports/${id}/definition`, null, {
    params: { selected_text: selectedText },
  });
  return response.data;
};

export interface ChatOptions {
  history?: Array<Pick<ChatMessage, 'role' | 'content'>>;
  webSearch?: boolean;
  persist?: boolean;
}

export const chatWithReports = async (
  question: string,
  reportIds?: number[],
  options: ChatOptions = {},
): Promise<ChatAnswer> => {
  const response = await axios.post(`${API_URL}/chat`, {
    question,
    report_ids: reportIds,
    history: options.history,
    web_search: options.webSearch ?? false,
    persist: options.persist ?? true,
  });
  return response.data;
};

export interface LlmInfo {
  provider: string;
  web_search: boolean;
  backend: string;
}

export const getLlmInfo = async (): Promise<LlmInfo> => {
  const response = await axios.get(`${API_URL}/llm/info`);
  return response.data;
};

export const getChatMessages = async (): Promise<ChatMessage[]> => {
  const response = await axios.get(`${API_URL}/chat/messages`);
  return response.data;
};

export const getNotes = async (): Promise<Note[]> => {
  const response = await axios.get(`${API_URL}/notes`);
  return response.data;
};

export const createNote = async (
  reportId: number,
  payload: { kind: string; source_text: string; content: string },
): Promise<Note> => {
  const response = await axios.post(`${API_URL}/reports/${reportId}/notes`, payload);
  return response.data;
};

export const deleteNote = async (noteId: number): Promise<void> => {
  await axios.delete(`${API_URL}/notes/${noteId}`);
};

export interface MailInfo {
  configured: boolean;
  missing: string[];
  host: string | null;
  port: number;
  security: string;
  authenticated: boolean;
  sender: string | null;
  recipients_count: number;
  auto_send: boolean;
}

export interface SendNewsletterResult {
  report_id: number;
  subject: string;
  recipients_count: number;
  newsletter_sent_at: string | null;
}

export const getMailInfo = async (): Promise<MailInfo> => {
  const response = await axios.get(`${API_URL}/mail/info`);
  return response.data;
};

export const sendReportNewsletter = async (id: number): Promise<SendNewsletterResult> => {
  const response = await axios.post(`${API_URL}/reports/${id}/send`);
  return response.data;
};

export const getReportNewsletter = async (id: number): Promise<string> => {
  const response = await axios.get(`${API_URL}/reports/${id}/newsletter`, { responseType: 'text' });
  return response.data;
};

export const downloadReportPdf = async (id: number): Promise<Blob> => {
  const response = await axios.get(`${API_URL}/reports/${id}/pdf`, {
    responseType: 'blob',
  });
  return response.data;
};

export const downloadReportDocx = async (id: number): Promise<Blob> => {
  const response = await axios.get(`${API_URL}/reports/${id}/docx`, {
    responseType: 'blob',
  });
  return response.data;
};

export interface NewsItem {
  id: number;
  report_id: number | null;
  position: number;
  title: string;
  maturity?: string | null;
  content: string;
  saved: boolean;
  saved_at?: string | null;
  created_at: string;
  report_date?: string | null;
}

export const getNews = async (params?: { saved?: boolean; reportId?: number }): Promise<NewsItem[]> => {
  const response = await axios.get(`${API_URL}/news`, {
    params: { saved: params?.saved, report_id: params?.reportId },
  });
  return response.data;
};

export const getReportNews = async (reportId: number): Promise<NewsItem[]> => {
  const response = await axios.get(`${API_URL}/reports/${reportId}/news`);
  return response.data;
};

export const setNewsSaved = async (newsId: number, saved: boolean): Promise<NewsItem> => {
  const response = await axios.patch(`${API_URL}/news/${newsId}`, { saved });
  return response.data;
};
