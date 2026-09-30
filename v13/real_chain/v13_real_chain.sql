-- real_chain load DML. Not a prelude. Not a per-session insert.
-- Copies live default version 1 thresholds, appends the eight read bands,
-- freezes version 2. Inserts the four read tools by name.
-- Does not UPDATE an existing mismatched row. Does not disable spawn_subsession.
-- Does not write a turn_budget max_cycles seed.

DO $seed$
DECLARE
  v_want_name text;
  v_want_desc text;
  v_want_handler text;
  v_want_spec jsonb;
  v_have_kind text;
  v_have_desc text;
  v_have_handler text;
  v_have_spec jsonb;
  v_have_enabled boolean;
  v_state text;
  v_extra int;
  v_missing int;
  v_pi jsonb;
  v_duck jsonb;
BEGIN
  v_pi := jsonb_build_object(
    'path', jsonb_build_object(
      'question', 'Which fixture file should be read?',
      'stated', 'Does the user name a fixture file to read?',
      'options', jsonb_build_object(
        'hello.txt', 'LF fixture',
        'crlf.txt', 'CRLF fixture')));
  v_duck := jsonb_build_object(
    'path', jsonb_build_object(
      'question', 'Which fixture file should be read?',
      'stated', 'Does the user name a fixture file to read?',
      'options', jsonb_build_object('fib.py', 'Python fixture')));

  FOR v_want_name, v_want_desc, v_want_handler, v_want_spec IN
    SELECT *
      FROM (VALUES
        ('read_pi',
         'Read a text file with Pi line slicing and truncation.',
         'worker:read_pi',
         v_pi),
        ('read_file_swift',
         'Read a text file with the headless line contract (swift).',
         'worker:read_file_swift',
         v_pi),
        ('read_file_py',
         'Read a text file with the headless line contract (python).',
         'worker:read_file_py',
         v_pi),
        ('read_duck',
         'Read a source file with the DuckDB AST block contract.',
         'worker:read_duck',
         v_duck)
      ) AS row(name, description, handler, param_spec)
  LOOP
    SELECT kind, description, handler, param_spec, enabled
      INTO v_have_kind, v_have_desc, v_have_handler, v_have_spec, v_have_enabled
      FROM public.tools
     WHERE name = v_want_name;
    IF NOT FOUND THEN
      INSERT INTO public.tools (name, description, kind, handler, param_spec, enabled)
      VALUES (v_want_name, v_want_desc, 'tool', v_want_handler, v_want_spec, true);
    ELSIF v_have_kind IS DISTINCT FROM 'tool'
          OR v_have_desc IS DISTINCT FROM v_want_desc
          OR v_have_handler IS DISTINCT FROM v_want_handler
          OR v_have_spec IS DISTINCT FROM v_want_spec
          OR v_have_enabled IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'v13: real chain: tool drift';
    END IF;
  END LOOP;

  IF (SELECT count(*) FROM public.tools
       WHERE name IN ('read_pi', 'read_file_swift', 'read_file_py', 'read_duck')) <> 4 THEN
    RAISE EXCEPTION 'v13: real chain: tools';
  END IF;

  SELECT state INTO v_state
    FROM public.v13_route_policies
   WHERE policy_name = 'default' AND policy_version = 2;

  IF NOT FOUND THEN
    INSERT INTO public.v13_route_policies (policy_name, policy_version)
    VALUES ('default', 2);
    INSERT INTO public.thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
    SELECT 'default', 2, signal, band_no, lo, hi, action
      FROM public.thresholds
     WHERE policy_name = 'default' AND policy_version = 1;
    INSERT INTO public.thresholds (policy_name, policy_version, signal, band_no, lo, hi, action)
    VALUES
      ('default', 2, 'param::read_pi::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'stated::read_pi::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'param::read_file_swift::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'stated::read_file_swift::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'param::read_file_py::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'stated::read_file_py::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'param::read_duck::path', 1, 0.60, 'Infinity', 'pass'),
      ('default', 2, 'stated::read_duck::path', 1, 0.60, 'Infinity', 'pass');
    UPDATE public.v13_route_policies SET state = 'frozen'
     WHERE policy_name = 'default' AND policy_version = 2;
  ELSE
    IF v_state IS DISTINCT FROM 'frozen' THEN
      RAISE EXCEPTION 'v13: real chain: route policy drift';
    END IF;
    SELECT count(*) INTO v_extra
      FROM (
        SELECT signal, band_no, lo, hi, action
          FROM public.thresholds
         WHERE policy_name = 'default' AND policy_version = 2
        EXCEPT
        SELECT signal, band_no, lo, hi, action
          FROM (
            SELECT signal, band_no, lo, hi, action
              FROM public.thresholds
             WHERE policy_name = 'default' AND policy_version = 1
            UNION ALL
            SELECT *
              FROM (VALUES
                ('param::read_pi::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_pi::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('param::read_file_swift::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_file_swift::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('param::read_file_py::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_file_py::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('param::read_duck::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_duck::path', 1, 0.60::float8, 'Infinity'::float8, 'pass')
              ) AS band(signal, band_no, lo, hi, action)
          ) expected
      ) extra;
    SELECT count(*) INTO v_missing
      FROM (
        SELECT signal, band_no, lo, hi, action
          FROM (
            SELECT signal, band_no, lo, hi, action
              FROM public.thresholds
             WHERE policy_name = 'default' AND policy_version = 1
            UNION ALL
            SELECT *
              FROM (VALUES
                ('param::read_pi::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_pi::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('param::read_file_swift::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_file_swift::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('param::read_file_py::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_file_py::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('param::read_duck::path', 1, 0.60::float8, 'Infinity'::float8, 'pass'),
                ('stated::read_duck::path', 1, 0.60::float8, 'Infinity'::float8, 'pass')
              ) AS band(signal, band_no, lo, hi, action)
          ) expected
        EXCEPT
        SELECT signal, band_no, lo, hi, action
          FROM public.thresholds
         WHERE policy_name = 'default' AND policy_version = 2
      ) missing;
    IF v_extra <> 0 OR v_missing <> 0 THEN
      RAISE EXCEPTION 'v13: real chain: route policy drift';
    END IF;
  END IF;
END
$seed$;
