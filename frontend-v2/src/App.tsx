import React, { useState, useEffect } from 'react';
import { HomePage } from '@/pages/HomePage';
import { MiningDashboardPage } from '@/pages/MiningDashboardPage';
import { FactorLibraryPage } from '@/pages/FactorLibraryPage';
import { BacktestPage } from '@/pages/BacktestPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { RunHistoryPage } from '@/pages/RunHistoryPage';
import { ProductionModelsPage } from '@/pages/ProductionModelsPage';
import { Layout } from '@/components/layout/Layout';
import type { PageId } from '@/components/layout/Layout';
import { ParticleBackground } from '@/components/ParticleBackground';
import { TaskProvider, useTaskContext } from '@/context/TaskContext';

// Inner component to access context
const AppContent: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<PageId>('home');
  const { miningTask } = useTaskContext();

  // Auto-switch to dashboard when a new mining task starts.
  // Triggers on taskId change so a user who clicks a fresh "Start" while
  // on home is taken to the dashboard immediately (the placeholder
  // "pending-…" task gives us a fresh taskId before the create-task API
  // call resolves, so the switch happens with no perceived delay and
  // there's no window where the previous run's data is visible).
  useEffect(() => {
    if (miningTask && miningTask.status === 'running' && currentPage === 'home') {
      setCurrentPage('mining_dashboard');
    }
  }, [miningTask?.taskId]);

  return (
    <>
      <ParticleBackground />
      {/*
        Use display:none to hide non-current pages instead of conditional unmounting.
        This ensures that components are not unmounted when switching pages, so WebSocket/task state is not lost.
      */}
      <div style={{ display: currentPage === 'home' ? 'block' : 'none' }}>
        <HomePage onNavigate={setCurrentPage} />
      </div>
      <div style={{ display: currentPage === 'mining_dashboard' ? 'block' : 'none' }}>
        <MiningDashboardPage onNavigate={setCurrentPage} />
      </div>
      <div style={{ display: currentPage === 'history' ? 'block' : 'none' }}>
        <RunHistoryPage onNavigate={setCurrentPage} />
      </div>
      <div style={{ display: currentPage === 'bundles' ? 'block' : 'none' }}>
        <ProductionModelsPage onNavigate={setCurrentPage} />
      </div>
      <div style={{ display: currentPage === 'library' ? 'block' : 'none' }}>
        <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
          <FactorLibraryPage />
        </Layout>
      </div>
      <div style={{ display: currentPage === 'backtest' ? 'block' : 'none' }}>
        <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
          <BacktestPage />
        </Layout>
      </div>
      <div style={{ display: currentPage === 'settings' ? 'block' : 'none' }}>
        <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
          <SettingsPage />
        </Layout>
      </div>
    </>
  );
};

export const App: React.FC = () => {
  return (
    <TaskProvider>
      <AppContent />
    </TaskProvider>
  );
};
