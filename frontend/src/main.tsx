import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import App from './App'
import Ingest from './pages/Ingest'
import DatasetPage from './pages/Dataset'
import Ask from './pages/Ask'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Ingest /> },
      { path: 'data/:id', element: <DatasetPage /> },
      { path: 'ask/:id', element: <Ask /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
