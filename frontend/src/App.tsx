import React, { useState, useEffect } from 'react';
import { LoginForm } from './components/LoginForm';
import { Dashboard } from './components/Dashboard';

export const App: React.FC = () => {
  const [token, setToken] = useState<string | null>(localStorage.getItem('bh_token'));
  const [email, setEmail] = useState<string | null>(localStorage.getItem('bh_email'));
  const [checking, setChecking] = useState<boolean>(true);

  useEffect(() => {
    const checkAuth = async () => {
      const storedToken = localStorage.getItem('bh_token');
      if (storedToken) {
        try {
          const res = await fetch('/api/auth/me', {
            headers: { Authorization: `Bearer ${storedToken}` },
          });
          const data = await res.json();
          if (res.ok) {
            setToken(storedToken);
            setEmail(data.email);
          } else {
            handleLogout();
          }
        } catch {
          handleLogout();
        }
      }
      setChecking(false);
    };
    checkAuth();
  }, []);

  const handleLoginSuccess = (newToken: string, data: any) => {
    setToken(newToken);
    setEmail(data.email);
  };

  const handleLogout = () => {
    localStorage.removeItem('bh_token');
    localStorage.removeItem('bh_email');
    setToken(null);
    setEmail(null);
  };

  if (checking) {
    return (
      <div className="min-h-screen bg-[#0b0f17] flex flex-col items-center justify-center text-slate-400 gap-3">
        <div className="relative flex items-center justify-center">
          <div className="w-10 h-10 border-2 border-cyan-500/30 border-t-cyan-400 rounded-full animate-spin" />
          <div className="absolute inset-0 w-10 h-10 border-2 border-cyan-400/10 rounded-full blur-sm" />
        </div>
        <span className="text-xs font-mono text-slate-500 tracking-wider">SECURE SESSION CHECK</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0b0f17] text-slate-100 selection:bg-cyan-500/30 selection:text-cyan-200">
      {token && email ? (
        <Dashboard token={token} email={email} onLogout={handleLogout} />
      ) : (
        <LoginForm onLoginSuccess={handleLoginSuccess} />
      )}
    </div>
  );
};

export default App;
