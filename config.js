// ============================================================
// PEGA AQUÍ TUS DOS CLAVES DE SUPABASE
// (Supabase → tu proyecto → Project Settings → API)
// ============================================================
var SUPABASE_URL = "PEGA_AQUI_TU_PROJECT_URL";
var SUPABASE_KEY = "PEGA_AQUI_TU_ANON_KEY";

var sb = (typeof supabase !== "undefined" && SUPABASE_URL.indexOf("http") === 0)
  ? supabase.createClient(SUPABASE_URL, SUPABASE_KEY)
  : null;
