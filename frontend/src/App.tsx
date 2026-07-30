import React, { useState, useEffect } from 'react';
import { MobileBlocked } from './components/MobileBlocked';
import { DesktopSessionStepper } from './components/DesktopSessionStepper';
import { Dashboard } from './components/Dashboard';

export const App: React.FC = () => {
  const [token, setToken] = useState<string | null>(localStorage.getItem('bh_token'));
  const [email, setEmail] = useState<string | null>(localStorage.getItem('bh_email'));
  const [childrenList, setChildrenList] = useState<any[]>([]);
  const [checking, setChecking] = useState<boolean>(true);
  const [isMobile, setIsMobile] = useState<boolean>(false);

  useEffect(() => {
    const checkMobile = () => {
      const mobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
      const smallScreen = window.innerWidth < 768;
      setIsMobile(mobileUA || smallScreen);
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);

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
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  const handleSessionSuccess = (userEmail: string, discoveredChildren?: any[]) => {
    const dummyToken = 'device_session_' + Date.now();
    localStorage.setItem('bh_token', dummyToken);
    localStorage.setItem('bh_email', userEmail);
    setToken(dummyToken);
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

  if (isMobile) {
    return <MobileBlocked />;
  }

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
        <DesktopSessionStepper onSuccess={handleSessionSuccess} />
      )}
    </div>
  );
};

export default App;
