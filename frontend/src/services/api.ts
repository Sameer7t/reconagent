import axios from 'axios';
import {
  CaseSummary,
  ThreeWayMatchData,
  InvestigationData,
  MetricCounts,
  DocumentContentData,
  ReviewDecisionRecord,
} from '../types';

const client = axios.create({
  baseURL: '', // Proxied via Vite to http://127.0.0.1:8000
  headers: {
    'Content-Type': 'application/json',
  },
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const api = {
  // Auth
  async login(username: string, password: string):Promise<{access_token: string}> {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    const res = await client.post('/auth/token', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });
    return res.data;
  },
  async getMe(): Promise<{id:string, email:string, role:string, created_at:string, is_active:boolean}> {
    const res = await client.get('/auth/me');
    return res.data;
  },
  async getUsers(): Promise<Array<{id: string, email: string, role: string, created_at: string, is_active: boolean}>> {
    const res = await client.get('/auth/users');
    return res.data;
  },
  async createUser(data: {email: string, password: string, role: string}): Promise<{id: string, email: string, role: string, created_at: string, is_active: boolean}> {
    const res = await client.post('/auth/users', data);
    return res.data;
  },
  async deleteUser(userId: string): Promise<{message: string}> {
    const res = await client.delete(`/auth/users/${userId}`);
    return res.data;
  },
  // 1. Health & Status
  async getHealth() {
    const res = await client.get('/health');
    return res.data;
  },

  // 2. Cases Directory
  async getCases(params?: {
    status?: string;
    requires_review?: boolean;
    search?: string;
    start_date?: string;
    end_date?: string;
    start_time?: string;
    end_time?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ total: number; cases: CaseSummary[] }> {
    const res = await client.get('/cases', { params });
    return res.data;
  },

  // 3. Case Details
  async getCaseDetail(caseId: string): Promise<any> {
    const res = await client.get(`/cases/${encodeURIComponent(caseId)}`);
    return res.data;
  },

  // 4. Autonomous Agent Investigation
  async getInvestigation(caseId: string): Promise<any> {
    const res = await client.get(`/cases/${encodeURIComponent(caseId)}/investigation`);
    return res.data;
  },

  // 5. Review Queue & Metrics
  async getReviewQueue(status = 'ALL'): Promise<any> {
    const res = await client.get('/review-queue', { params: { status } });
    return res.data;
  },

  async getReviewMetrics(): Promise<MetricCounts> {
    try {
      const res = await client.get('/review/metrics');
      const data = res.data;
      const total = typeof data.total_count === 'number' ? data.total_count : 0;
      const matched = typeof data.auto_approved_count === 'number' ? data.auto_approved_count : 0;
      const underReview = typeof data.pending_count === 'number' ? data.pending_count : 0;
      const discrepancies = Math.max(0, total - matched);
      return {
        total_cases: total,
        matched: matched,
        discrepancies: discrepancies,
        under_review: underReview,
      };
    } catch {
      return {
        total_cases: 0,
        matched: 0,
        discrepancies: 0,
        under_review: 0,
      };
    }
  },

  // 6. Specialist Settlement Actions (Approve, Reject, Escalate)
  async submitDecision(
    caseId: string,
    action: 'APPROVE' | 'REJECT' | 'ESCALATE',
    reviewerId: string,
    notes: string
  ): Promise<any> {
    const payload = {
      reviewer_id: reviewerId,
      notes: notes,
    };

    if (action === 'APPROVE') {
      const res = await client.post(`/review-queue/${encodeURIComponent(caseId)}/approve`, payload);
      return res.data;
    } else if (action === 'REJECT') {
      const res = await client.post(`/review-queue/${encodeURIComponent(caseId)}/reject`, payload);
      return res.data;
    } else {
      const res = await client.post(`/review-queue/${encodeURIComponent(caseId)}/escalate`, payload);
      return res.data;
    }
  },

  // 7. Click-to-View Source Document Content
  async getDocumentContent(fileName?: string, filePath?: string): Promise<DocumentContentData> {
    const res = await client.get('/documents/content', {
      params: {
        file_name: fileName,
        file_path: filePath,
      },
    });
    return res.data;
  },

  // 8. Ingestion & Reconciliation
  async uploadMixedFiles(files: File[]): Promise<any> {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    const res = await client.post('/cases/reconcile-mixed', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },

  async reconcileTriplet(
    poFile: File,
    invoiceFile: File,
    receiptFiles: File[]
  ): Promise<any> {
    const formData = new FormData();
    formData.append('purchase_order_file', poFile);
    formData.append('po_file', poFile);
    formData.append('invoice_file', invoiceFile);
    receiptFiles.forEach((f) => formData.append('receipt_files', f));

    const res = await client.post('/cases/reconcile-triplet', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;
  },
};

