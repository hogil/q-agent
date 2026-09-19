import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import DocumentPage from './DocumentPage';
import './styles.css';
import './investigationBoard.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {new URLSearchParams(location.search).get('view') === 'document' ? (
      <DocumentPage />
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
