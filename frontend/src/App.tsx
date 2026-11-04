import { useEffect, useMemo, useState, type JSX } from 'react';
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import {
  Button,
  FluentProvider,
  Hamburger,
  NavDrawer,
  NavDrawerBody,
  NavDrawerHeader,
  NavItem,
  NavSectionHeader,
  Subtitle1,
  Text,
  Tooltip,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowSwap20Regular,
  ArrowSyncCircle20Regular,
  ChatMultiple20Regular,
  CloudArrowUp20Regular,
  Delete20Regular,
  Gauge20Regular,
  History20Regular,
  Home20Regular,
  ClipboardTaskListLtr20Regular,
  Rocket20Regular,
  WeatherMoon20Regular,
  WeatherSunny20Regular,
} from '@fluentui/react-icons';
import ComparePage from './pages/Compare';
import DeployPage from './pages/Deploy';
import EnvironmentDetailPage from './pages/EnvironmentDetail';
import ExercisePage from './pages/Exercise';
import ExperimentHistoryPage from './pages/ExperimentHistory';
import OverviewPage from './pages/Overview';
import PerformanceReportPage from './pages/PerformanceReport';
import PerformanceRunPage from './pages/PerformanceRun';
import ProvisionPage from './pages/Provision';
import QualityReportPage from './pages/QualityReport';
import QualityRunPage from './pages/QualityRun';
import RetunePage from './pages/Retune';
import TeardownPage from './pages/Teardown';
import { THEMES, getStoredColorScheme, storeColorScheme, type ColorSchemeName } from './theme';

const NARROW_VIEWPORT_QUERY = '(max-width: 900px)';

type NavLeaf = {
  value: string;
  label: string;
  icon: JSX.Element;
};

type NavGroup = {
  key: string;
  label: string;
  items: NavLeaf[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    key: 'setup',
    label: 'Setup',
    items: [
      { value: '/provision', label: 'Provision', icon: <CloudArrowUp20Regular /> },
      { value: '/deploy', label: 'Deploy', icon: <Rocket20Regular /> },
    ],
  },
  {
    key: 'operate',
    label: 'Operate',
    items: [
      { value: '/exercise', label: 'Exercise', icon: <ChatMultiple20Regular /> },
      { value: '/retune', label: 'Retune', icon: <ArrowSyncCircle20Regular /> },
    ],
  },
  {
    key: 'evaluate',
    label: 'Evaluate',
    items: [
      { value: '/quality/run', label: 'Quality Run', icon: <ClipboardTaskListLtr20Regular /> },
      { value: '/performance/run', label: 'Performance Run', icon: <Gauge20Regular /> },
      { value: '/compare', label: 'Compare', icon: <ArrowSwap20Regular /> },
    ],
  },
  {
    key: 'manage',
    label: 'Manage',
    items: [
      { value: '/history', label: 'Experiment History', icon: <History20Regular /> },
      { value: '/teardown', label: 'Teardown', icon: <Delete20Regular /> },
    ],
  },
];

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    minHeight: '100vh',
    backgroundColor: tokens.colorNeutralBackground3,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: tokens.spacingHorizontalM,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalXXL}`,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  headerStart: {
    display: 'flex',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
  },
  brand: {
    display: 'flex',
    flexDirection: 'column',
  },
  body: {
    display: 'flex',
    flex: 1,
    minHeight: 0,
  },
  main: {
    flex: 1,
    minWidth: 0,
    padding: tokens.spacingVerticalXXL,
    paddingTop: tokens.spacingVerticalXL,
  },
  mainInner: {
    maxWidth: '72rem',
    marginInline: 'auto',
  },
  skipLink: {
    position: 'absolute',
    top: 0,
    left: 0,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    backgroundColor: tokens.colorNeutralBackground1,
    color: tokens.colorNeutralForeground1,
    zIndex: 100,
    transform: 'translateY(-150%)',
    transitionProperty: 'transform',
    transitionDuration: tokens.durationFast,
    ':focus': {
      transform: 'translateY(0)',
    },
  },
});

function useColorScheme() {
  const [scheme, setScheme] = useState<ColorSchemeName>(() => getStoredColorScheme());

  useEffect(() => {
    storeColorScheme(scheme);
  }, [scheme]);

  return {
    scheme,
    toggle: () => setScheme((current) => (current === 'light' ? 'dark' : 'light')),
  };
}

function useIsNarrowViewport() {
  const [isNarrow, setIsNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(NARROW_VIEWPORT_QUERY).matches,
  );

  useEffect(() => {
    const query = window.matchMedia(NARROW_VIEWPORT_QUERY);
    const listener = (event: MediaQueryListEvent) => setIsNarrow(event.matches);
    query.addEventListener('change', listener);
    return () => query.removeEventListener('change', listener);
  }, []);

  return isNarrow;
}

type ShellProps = {
  scheme: ColorSchemeName;
  onToggleScheme: () => void;
};

function Shell({ scheme, onToggleScheme }: ShellProps) {
  const styles = useStyles();
  const navigate = useNavigate();
  const location = useLocation();
  const isNarrow = useIsNarrowViewport();
  const [drawerOpen, setDrawerOpen] = useState(!isNarrow);

  useEffect(() => {
    setDrawerOpen(!isNarrow);
  }, [isNarrow]);

  const selectedValue = useMemo(() => {
    const match = NAV_GROUPS.flatMap((group) => group.items).find(
      (item) => location.pathname === item.value || location.pathname.startsWith(`${item.value}/`),
    );
    return match?.value ?? (location.pathname === '/' ? '/' : '');
  }, [location.pathname]);

  return (
    <div className={styles.root}>
      <a href="#main-content" className={styles.skipLink}>
        Skip to main content
      </a>
      <header className={styles.header}>
        <div className={styles.headerStart}>
          <Hamburger onClick={() => setDrawerOpen((open) => !open)} />
          <div className={styles.brand}>
            <Text size={200}>Learning environment</Text>
            <Subtitle1 as="h1">Azure LLM Serving Demo</Subtitle1>
          </div>
        </div>
        <Tooltip content={scheme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'} relationship="label">
          <Button
            appearance="subtle"
            shape="circular"
            icon={scheme === 'light' ? <WeatherMoon20Regular /> : <WeatherSunny20Regular />}
            onClick={onToggleScheme}
            aria-label={scheme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
          />
        </Tooltip>
      </header>
      <div className={styles.body}>
        <NavDrawer
          open={drawerOpen}
          type={isNarrow ? 'overlay' : 'inline'}
          selectedValue={selectedValue}
          onNavItemSelect={(event, data) => {
            event.preventDefault();
            navigate(data.value);
            if (isNarrow) {
              setDrawerOpen(false);
            }
          }}
          aria-label="Primary"
        >
          <NavDrawerHeader />
          <NavDrawerBody>
            <NavItem value="/" href="/" icon={<Home20Regular />}>
              Overview
            </NavItem>
            {NAV_GROUPS.map((group) => (
              <div key={group.key}>
                <NavSectionHeader>{group.label}</NavSectionHeader>
                {group.items.map((item) => (
                  <NavItem key={item.value} value={item.value} href={item.value} icon={item.icon}>
                    {item.label}
                  </NavItem>
                ))}
              </div>
            ))}
          </NavDrawerBody>
        </NavDrawer>
        <main className={styles.main} id="main-content" tabIndex={-1}>
          <div className={styles.mainInner}>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/provision" element={<ProvisionPage />} />
              <Route path="/environments" element={<EnvironmentDetailPage />} />
              <Route path="/environments/:environmentId" element={<EnvironmentDetailPage />} />
              <Route path="/deploy" element={<DeployPage />} />
              <Route path="/exercise" element={<ExercisePage />} />
              <Route path="/quality/run" element={<QualityRunPage />} />
              <Route path="/quality/report/:runId" element={<QualityReportPage />} />
              <Route path="/performance/run" element={<PerformanceRunPage />} />
              <Route path="/performance/report/:runId" element={<PerformanceReportPage />} />
              <Route path="/retune" element={<RetunePage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/teardown" element={<TeardownPage />} />
              <Route path="/history" element={<ExperimentHistoryPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  );
}

function ThemedApp() {
  const { scheme, toggle } = useColorScheme();
  return (
    <FluentProvider theme={THEMES[scheme]} style={{ minHeight: '100vh' }}>
      <Shell scheme={scheme} onToggleScheme={toggle} />
    </FluentProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemedApp />
    </BrowserRouter>
  );
}
