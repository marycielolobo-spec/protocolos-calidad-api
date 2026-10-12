insert into empresa (nombre, es_externa) values
  ('Stracon', false), ('Hudbay', true), ('Knight Piésold', true)
on conflict (nombre) do nothing;

-- Las 3 combinaciones de firmantes vistas hasta hoy. Se asigna por tipo (default) o por proyecto/contrato (override).
insert into plantilla_firma (codigo, nombre, roles) values
  ('STRACON_OPS_KP', 'Calidad Stracon + Operaciones Stracon + Knight Piésold', '[
     {"rol":"elaborado","empresa":"Stracon","area":"Calidad","canal":"app"},
     {"rol":"revisado_aprobado","empresa":"Stracon","area":"Operaciones","canal":"app"},
     {"rol":"aceptado","empresa":"Knight Piésold","area":"Supervisión","canal":"acrobat_sign"}]'),
  ('CALIDAD_KP_HUDBAY', 'Calidad Stracon + Knight Piésold + Operaciones Hudbay', '[
     {"rol":"elaborado","empresa":"Stracon","area":"Calidad","canal":"app"},
     {"rol":"revisado_aprobado","empresa":"Knight Piésold","area":"Supervisión","canal":"acrobat_sign"},
     {"rol":"aceptado","empresa":"Hudbay","area":"Operaciones","canal":"acrobat_sign"}]'),
  ('STRACON_OPS_HUDBAY', 'Calidad Stracon + Operaciones Stracon + Hudbay (supervisión directa)', '[
     {"rol":"elaborado","empresa":"Stracon","area":"Calidad","canal":"app"},
     {"rol":"revisado_aprobado","empresa":"Stracon","area":"Operaciones","canal":"app"},
     {"rol":"aceptado","empresa":"Hudbay","area":"Supervisión","canal":"acrobat_sign"}]')
on conflict (codigo) do nothing;

insert into proyecto (nombre, cliente, codigo_contrato, entregable_area, estructura_frente) values
  ('MINA CONSTANCIA', 'HUDBAY PERU S.A.C.', '10203002',
   'DEPOSITO DE RELAVES (TMF) - ETAPA VIII', 'DIQUE DEL DEPOSITO DE RELAVES (TMF)');
