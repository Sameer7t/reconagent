import React, { useState, useEffect } from 'react';
import { 
  X, 
  UserPlus, 
  Trash2, 
  ShieldCheck, 
  Eye, 
  CheckCircle2, 
  AlertCircle, 
  Users, 
  Lock, 
  User as UserIcon,
  Clock
} from 'lucide-react';
import { api } from '../services/api';
import { useAuth } from '../AuthContext';

interface UserItem {
  id: string;
  email: string;
  role: string;
  created_at: string;
  is_active: boolean;
}

interface UserManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const UserManagementModal: React.FC<UserManagementModalProps> = ({ isOpen, onClose }) => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // New user form state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<'Admin' | 'Reviewer' | 'Viewer'>('Reviewer');
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getUsers();
      setUsers(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchUsers();
      setEmail('');
      setPassword('');
      setError(null);
      setSuccess(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required');
      return;
    }

    try {
      setCreating(true);
      setError(null);
      setSuccess(null);
      await api.createUser({
        email: email.trim(),
        password: password.trim(),
        role,
      });
      setSuccess(`User "${email}" created successfully as ${role}!`);
      setEmail('');
      setPassword('');
      setRole('Reviewer');
      await fetchUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create user');
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteUser = async (userToDelete: UserItem) => {
    if (userToDelete.id === currentUser?.id) {
      setError('You cannot delete your own logged-in admin account.');
      return;
    }

    if (!confirm(`Are you sure you want to permanently delete user "${userToDelete.email}"?`)) {
      return;
    }

    try {
      setDeletingId(userToDelete.id);
      setError(null);
      setSuccess(null);
      await api.deleteUser(userToDelete.id);
      setSuccess(`User "${userToDelete.email}" deleted successfully.`);
      await fetchUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete user');
    } finally {
      setDeletingId(null);
    }
  };

  const getRoleBadge = (userRole: string) => {
    switch (userRole) {
      case 'Admin':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
            <ShieldCheck className="w-3 h-3 mr-1" />
            Admin
          </span>
        );
      case 'Reviewer':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30">
            <CheckCircle2 className="w-3 h-3 mr-1" />
            Reviewer
          </span>
        );
      case 'Viewer':
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
            <Eye className="w-3 h-3 mr-1" />
            Viewer
          </span>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/50">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-500/20 rounded-xl text-indigo-400 border border-indigo-500/30">
              <Users className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-wide">User Management & Permissions</h2>
              <p className="text-xs text-slate-400">Admin control panel for managing users and role-based access</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Alerts */}
        {error && (
          <div className="mx-6 mt-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center space-x-2 text-rose-300 text-xs">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {success && (
          <div className="mx-6 mt-4 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center space-x-2 text-emerald-300 text-xs">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span>{success}</span>
          </div>
        )}

        <div className="p-6 overflow-y-auto space-y-6">
          {/* New User Provisioning Form */}
          <div className="bg-slate-800/40 border border-slate-800/80 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-200 flex items-center space-x-2 mb-4">
              <UserPlus className="w-4 h-4 text-indigo-400" />
              <span>Create New User</span>
            </h3>

            <form onSubmit={handleCreateUser} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">Email</label>
                <div className="relative">
                  <UserIcon className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
                  <input
                    type="email"
                    required
                    placeholder="e.g. admin@reconagent.local"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">Password</label>
                <div className="relative">
                  <Lock className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
                  <input
                    type="password"
                    required
                    placeholder="Enter password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">Assigned Role</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as any)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500 transition"
                >
                  <option value="Admin">Admin (Full Access & User Mgmt)</option>
                  <option value="Reviewer">Reviewer (Upload, Investigate, Review)</option>
                  <option value="Viewer">Viewer (Read-Only Access)</option>
                </select>
              </div>

              <div>
                <button
                  type="submit"
                  disabled={creating}
                  className="w-full py-2 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs shadow-md shadow-indigo-600/20 transition flex items-center justify-center space-x-1.5 disabled:opacity-50"
                >
                  <UserPlus className="w-4 h-4" />
                  <span>{creating ? 'Creating...' : 'Create Account'}</span>
                </button>
              </div>
            </form>

            {/* Role Descriptions Helper */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4 pt-4 border-t border-slate-800 text-[11px] text-slate-400">
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="font-semibold text-indigo-400 block mb-0.5">Admin Role</span>
                Full platform control, user creation & deletion, file upload, investigations, and governance approvals.
              </div>
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="font-semibold text-amber-400 block mb-0.5">Reviewer Role</span>
                Upload documents, run 3-way reconciliations, trigger AI investigations, and approve/reject cases.
              </div>
              <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
                <span className="font-semibold text-emerald-400 block mb-0.5">Viewer Role</span>
                Auditor & observer role with read-only access to view cases, audit logs, and investigation findings.
              </div>
            </div>
          </div>

          {/* User Directory */}
          <div className="bg-slate-800/40 border border-slate-800/80 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-200">Registered Accounts ({users.length})</h3>
              <button
                onClick={fetchUsers}
                className="text-xs text-indigo-400 hover:text-indigo-300 transition"
              >
                Refresh
              </button>
            </div>

            {loading ? (
              <div className="p-8 text-center text-slate-400 text-xs">Loading user list...</div>
            ) : users.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-xs">No registered users found.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-300">
                  <thead className="bg-slate-900/80 text-slate-400 font-semibold border-b border-slate-800">
                    <tr>
                      <th className="px-5 py-3">User</th>
                      <th className="px-5 py-3">Role</th>
                      <th className="px-5 py-3">Created On</th>
                      <th className="px-5 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800">
                    {users.map((u) => {
                      const isSelf = u.id === currentUser?.id || u.email === currentUser?.email;
                      return (
                        <tr key={u.id} className="hover:bg-slate-800/30 transition">
                          <td className="px-5 py-3 flex items-center space-x-3">
                            <div className="w-7 h-7 rounded-full bg-slate-700 flex items-center justify-center font-bold text-slate-200 uppercase text-xs">
                              {u.email[0]}
                            </div>
                            <div>
                              <div className="font-medium text-white flex items-center space-x-1.5">
                                <span>{u.email}</span>
                                {isSelf && (
                                  <span className="text-[10px] text-indigo-400 bg-indigo-500/10 px-1.5 py-0.2 rounded font-normal">
                                    You
                                  </span>
                                )}
                              </div>
                              <span className="text-[10px] text-slate-500 font-mono">ID: {u.id.slice(0, 8)}...</span>
                            </div>
                          </td>
                          <td className="px-5 py-3">
                            {getRoleBadge(u.role)}
                          </td>
                          <td className="px-5 py-3 text-slate-400 flex items-center space-x-1 mt-1">
                            <Clock className="w-3.5 h-3.5 text-slate-500" />
                            <span>{new Date(u.created_at).toLocaleString()}</span>
                          </td>
                          <td className="px-5 py-3 text-right">
                            {isSelf ? (
                              <span className="text-[11px] text-slate-500 italic">Active session</span>
                            ) : (
                              <button
                                onClick={() => handleDeleteUser(u)}
                                disabled={deletingId === u.id}
                                title={`Delete ${u.email}`}
                                className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition disabled:opacity-50"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
