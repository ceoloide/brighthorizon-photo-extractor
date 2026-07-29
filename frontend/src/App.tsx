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
      <div className="min-h-screen bg-slate-900 flex items-center justify-center text-slate-400">
        <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900">
      {token && email ? (
        <Dashboard token={token} email={email} onLogout={handleLogout} />
      ) : (
        <LoginForm onLoginSuccess={handleLoginSuccess} />
      )}
    </div>
  );
};

export default App;
