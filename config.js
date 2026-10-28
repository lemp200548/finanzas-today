// ============================================================
// PEGA AQUÍ TUS DOS CLAVES DE SUPABASE
// (Supabase → tu proyecto → Project Settings → API)
// ============================================================
var SUPABASE_URL = "https://igopcqzocsvkobfwsaja.supabase.co";
var SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlnb3BjcXpvY3N2a29iZndzYWphIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMxNTM2MDgsImV4cCI6MjEwODcyOTYwOH0.mpGGZr74gChi9gVSAh8gfdoXBNk4g7mFDQFnfXOP7wU";

var sb = (typeof supabase !== "undefined" && SUPABASE_URL.indexOf("http") === 0)
  ? supabase.createClient(SUPABASE_URL, SUPABASE_KEY)
  : null;
