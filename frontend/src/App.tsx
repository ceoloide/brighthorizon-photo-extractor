import React, { useState, useEffect } from 'react';
import { LoginForm } from './components/LoginForm';
import { Dashboard } from './components/Dashboard';

export const App: React.FC = () => {
  const [token, setToken] = useState<string | null>(localStorage.getItem('bh_token'));
  const [email, setEmail] = useState<string | null>(localStorage.getItem('bh_email'));
  const [childrenList, setChildrenList] = useState<any[]>([]);
  const [checking, setChecking] = useState<boolean>(true);

  useEffect(() => {
    const checkAuth = async () => {
      const storedToken = localStorage.getItem('bh_token');
      try {
        const res = await fetch('/api/auth/me', {
          headers: storedToken ? { Authorization: `Bearer ${storedToken}` } : {},
        });
        const data = await res.json();
        if (res.ok && data.authenticated) {
          const activeEmail = data.email || localStorage.getItem('bh_email');
          const activeToken = data.token || storedToken || 'device_session_authenticated';
          localStorage.setItem('bh_token', activeToken);
          if (activeEmail) localStorage.setItem('bh_email', activeEmail);
          setToken(activeToken);
          setEmail(activeEmail);
          if (data.children) setChildrenList(data.children);
        } else {
          handleLogout();
        }
      } catch {
        handleLogout();
      }
      setChecking(false);
    };

    checkAuth();
  }, []);

  const handleSessionSuccess = (userEmail: string, discoveredChildren?: any[], validToken?: string) => {
    const activeToken = validToken || 'device_session_' + Date.now();
    localStorage.setItem('bh_token', activeToken);
    localStorage.setItem('bh_email', userEmail);
    setToken(activeToken);
    setEmail(userEmail);
    if (discoveredChildren) setChildrenList(discoveredChildren);
  };

  const handleLogout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch {}
    localStorage.removeItem('bh_token');
    localStorage.removeItem('bh_email');
    setToken(null);
    setEmail(null);
    setChildrenList([]);
  };

  if (checking) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center text-slate-500 gap-3">
        <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs font-medium text-slate-600">Verifying session...</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 font-sans">
      {token && email ? (
        <Dashboard token={token} email={email} childrenList={childrenList} onLogout={handleLogout} />
      ) : (
        <LoginForm onLoginSuccess={(validToken, data) => handleSessionSuccess(data?.email || '', data?.children, validToken)} />
      )}
    </div>
  );
};

export default App;
