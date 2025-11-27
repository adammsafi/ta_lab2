SELECT table_name AS view_name
FROM information_schema.views
WHERE table_schema = 'public'
ORDER BY view_name;