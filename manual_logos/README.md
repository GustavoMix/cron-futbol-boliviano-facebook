# Escudos manuales

Pon acá las imágenes de los equipos que el cron nunca va a poder encontrar
solo (clubes chicos/regionales de Bolivia sin página en Wikipedia).

## Cómo nombrar el archivo

- El nombre del archivo (sin la extensión) es el nombre del equipo, con
  espacios reemplazados por `_`. Ejemplos:
  - `real_potosi.png`
  - `guabira.jpg`
  - `oriente_petrolero.png`
- No hace falta preocuparse por tildes ni mayúsculas — el cron normaliza
  el nombre igual que hace con todos los demás equipos.
- Formatos aceptados: `.png`, `.jpg`, `.jpeg`, `.webp`.

## Qué pasa después

En la próxima corrida del cron, cada imagen de esta carpeta se sube sola a
Supabase Storage (bucket `team-logos`) y queda asociada a ese equipo en la
tabla `team_logos`. No hace falta tocar código ni SQL — solo poner el
archivo acá y hacer commit/push.

## Lista actual de equipos sin escudo (generada 2026-08-20)

abb, academia_puerto_cabello, atl_independiente_cbba, atletico_del_beni,
atletico_juniors_yotala, atletico_sucre, barcelona, bragantino,
c_d_guadalajara, carabobo, caracas, chaco_f_c_pando, coquimbo_unido, cusco,
deportivo_a_y_b, deportivo_la_guaira, deportivo_tigres_f_c,
empresa_minera_huanuni, german_busch, guabira, highland_players,
i_n_san_juan_fc, juventud, kivon, libertad, libertad_f_c_pando,
noroeste_santa_nelly, o_higgins, oriente_petrolero, platense,
primero_de_mayo_f_c, recoleta, rio_san_juan_humi, san_antonio,
san_antonio_bulo_bulo, san_martin_yacuiba, santos,
the_strongest_guayaramerin, totora_real_oruro, union_tarija,
universidad_central, universitario_de_pando, universitario_de_tarija,
universitario_del_beni, universitario_sfxch

(No hace falta completar todos — solo los que te importen. Los que no
tengan imagen acá van a seguir mostrando la bandera del país como hasta
ahora.)
