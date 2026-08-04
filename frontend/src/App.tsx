import React, { useState, useEffect } from 'react';
import { LoginForm } from './components/LoginForm';
import { Dashboard } from './components/Dashboard';
import { Footer } from './components/Footer';

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
    const activeEmail = userEmail || localStorage.getItem('bh_email') || '';
    const activeToken = validToken || localStorage.getItem('bh_token') || 'device_session_' + Date.now();

    if (!activeEmail || !activeToken) {
      console.error('Missing activeEmail or activeToken in handleSessionSuccess!');
      return;
    }

    localStorage.setItem('bh_token', activeToken);
    localStorage.setItem('bh_email', activeEmail);
    document.cookie = `bh_tenant_token=${activeToken}; path=/; max-age=${86400 * 30}; SameSite=Lax`;
    setToken(activeToken);
    setEmail(activeEmail);
    if (discoveredChildren && discoveredChildren.length > 0) {
      setChildrenList(discoveredChildren);
    }
  };

  const handleLogout = async () => {
    const storedToken = localStorage.getItem('bh_token');
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: storedToken ? { Authorization: `Bearer ${storedToken}` } : {},
      });
    } catch {}
    localStorage.removeItem('bh_token');
    localStorage.removeItem('bh_email');
    document.cookie = 'bh_tenant_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
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
    <div className="min-h-screen bg-slate-50 text-slate-800 font-sans flex flex-col justify-between">
      <main className="flex-1 flex flex-col">
        {token && email ? (
          <Dashboard token={token} email={email} childrenList={childrenList} onLogout={handleLogout} />
        ) : (
          <LoginForm onLoginSuccess={(validToken, data) => handleSessionSuccess(data?.email || email || localStorage.getItem('bh_email') || '', data?.children, validToken)} />
        )}
      </main>
      <Footer />
    </div>
  );
};

export default App;
