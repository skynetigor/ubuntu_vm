import express from 'express';
import cors from 'cors';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import authRoutes from './routes/auth.js';
import workflowRoutes from './routes/workflows.js';
import executionRoutes from './routes/executions.js';
import deploymentRoutes from './routes/deployments.js';
import benchmarkRoutes from './routes/benchmarks.js';
import { requireAuth } from './middleware/auth.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();

app.use(cors());
app.use(express.json());

// Public routes
app.use('/api/auth', authRoutes);

// Protected routes
app.use('/api/workflows', requireAuth, workflowRoutes);
app.use('/api/executions', requireAuth, executionRoutes);
app.use('/api/deployments', requireAuth, deploymentRoutes);
app.use('/api/benchmarks', requireAuth, benchmarkRoutes);

// Angular SPA — static files then fallback
const publicDir = join(__dirname, '..', 'public');
app.use(express.static(publicDir));
app.get('*', (req, res) => {
  res.sendFile(join(publicDir, 'index.html'));
});

const port = process.env.PORT || 5000;
app.listen(port, () => console.log(`workflows-ui listening on :${port}`));
