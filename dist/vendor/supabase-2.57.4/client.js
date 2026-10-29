// The official browser bundle is served with the site, without a runtime CDN.
import './supabase.js';
export const createClient = globalThis.supabase.createClient;
