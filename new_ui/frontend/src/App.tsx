import { Suspense, lazy } from 'react'
import { LazyMotion, domAnimation } from 'framer-motion'
import {
  Outlet,
  RouterProvider,
  createBrowserRouter,
} from 'react-router-dom'
import { Toaster } from './components/common/Toaster'
import Layout from './components/layout/Layout'

const HomePage = lazy(() => import('./pages/HomePage'))
const PaperToCodePage = lazy(() => import('./pages/PaperToCodePage'))
const ChatPlanningPage = lazy(() => import('./pages/ChatPlanningPage'))
const WorkflowEditorPage = lazy(() => import('./pages/WorkflowEditorPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function RouteLayout() {
  return (
    <Layout>
      <Suspense fallback={<div className="py-20 text-center text-gray-500">Loading page...</div>}>
        <Outlet />
      </Suspense>
    </Layout>
  )
}

const router = createBrowserRouter([
  {
    path: '/',
    element: <RouteLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'paper-to-code', element: <PaperToCodePage /> },
      { path: 'chat', element: <ChatPlanningPage /> },
      { path: 'workflow', element: <WorkflowEditorPage /> },
      { path: 'settings', element: <SettingsPage /> },
    ],
  },
])

function App() {
  return (
    <LazyMotion features={domAnimation}>
      <RouterProvider router={router} />
      <Toaster />
    </LazyMotion>
  )
}

export default App
