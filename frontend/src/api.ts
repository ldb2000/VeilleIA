import axios from 'axios';

const API_URL = 'http://localhost:8000';

export interface Report {
  id: number;
  date: string;
  report_type: string;
  content: string;
  created_at: string;
}

export interface ReportSummary {
  report_id: number;
  summary: string;
  updated_at: string;
}

export interface ReportDetail {
  detail: string;
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

export const triggerReport = async (): Promise<Report> => {
  const response = await axios.post(`${API_URL}/reports/trigger`);
  return response.data;
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

export const chatWithReports = async (question: string, reportIds?: number[]): Promise<ChatAnswer> => {
  const response = await axios.post(`${API_URL}/chat`, {
    question,
    report_ids: reportIds,
  });
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

export const getReportPdfUrl = (id: number): string => {
  return `${API_URL}/reports/${id}/pdf`;
};
