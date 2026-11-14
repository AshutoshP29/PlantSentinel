import '@fontsource-variable/inter'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { AuthProvider, RequireAuth } from './components/AuthProvider'
import { Gate } from './components/Gate'
import Layout from './components/Layout'
import { ToastProvider } from './components/ToastProvider'
import './index.css'
import Agent from './pages/Agent'
import AssetDetail from './pages/AssetDetail'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import Login from './pages/Login'
import Privacy from './pages/Privacy'
import Roles from './pages/Roles'
import Upload from './pages/Upload'
import Users from './pages/Users'

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <ToastProvider>
          <Layout />
        </ToastProvider>
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Gate perm="view_dashboard"><Dashboard /></Gate> },
      { path: 'upload', element: <Gate perm="upload_data"><Upload /></Gate> },
      { path: 'assets/:tag', element: <Gate perm="view_dashboard"><AssetDetail /></Gate> },
      { path: 'agent', element: <Gate perm="ask_agent"><Agent /></Gate> },
      { path: 'documents', element: <Gate perm="view_documents"><Documents /></Gate> },
      { path: 'privacy', element: <Privacy /> },
      { path: 'users', element: <Gate perm="manage_users"><Users /></Gate> },
      { path: 'roles', element: <Roles /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </StrictMode>,
)
