const { readFileSync } = require('fs');
const { join } = require('path');

// Read template once at cold start
let htmlTemplate = null;

module.exports = function handler(req, res) {
  if (!htmlTemplate) {
    const filePath = join(__dirname, '..', 'geo-report-zadara.html');
    htmlTemplate = readFileSync(filePath, 'utf-8');
  }

  const html = htmlTemplate
    .replace('__SUPABASE_URL__', process.env.SUPABASE_URL || '')
    .replace('__SUPABASE_ANON_KEY__', process.env.SUPABASE_ANON_KEY || '');

  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=86400');
  res.status(200).send(html);
};
