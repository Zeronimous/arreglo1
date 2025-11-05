
import os
import csv
import re
import argparse
from pathlib import Path

# --- Lógica de Extracción Mejorada ---

# Regex para capturar diálogos de personajes (ej: `e "Hola"`)
# Captura el identificador del personaje y el texto.
DIALOGUE_REGEX = re.compile(r'^\s*([\w\d]+)\s+"((?:\\"|[^"])*)"', re.UNICODE)

# Regex para capturar texto de narrador (ej: `"Hola"`) y opciones de menú (ej: `"Sí":`)
# Es más simple y busca cualquier línea que comience con una cadena entre comillas.
NARRATOR_REGEX = re.compile(r'^\s*"((?:\\"|[^"])*)"', re.UNICODE)

# Conjunto de palabras clave que, si aparecen al inicio de una línea,
# indican que la línea es probablemente código y no texto traducible.
# Esto es más fiable que una expresión regular compleja.
NON_TRANSLATABLE_KEYWORDS = {
    'image', 'style', 'transform', 'scene', 'show', 'hide',
    'play', 'queue', 'stop', 'voice', 'sound', 'music',
    'font', 'size', 'color', 'define', 'default', 'persistent', '$',
    'python', 'init', 'screen', 'timer', 'on', 'if', 'while'
}


def find_rpy_files(directory):
    """Encuentra todos los archivos .rpy en el directorio y subdirectorios."""
    return sorted(Path(directory).rglob("*.rpy"))

def is_valid_text(text):
    """
    Una función de ayuda para filtrar cadenas que probablemente no necesiten traducción.
    Actúa como una segunda capa de filtrado después de la lógica principal.
    """
    if not text or text.isdigit():
        return False
    # Excluir rutas de archivo que puedan haberse colado
    if '/' in text and any(ext in text.lower() for ext in ['.png', '.jpg', '.ogg', '.ttf', '.webm']):
        return False
    # Excluir si es solo un placeholder de variable
    if re.fullmatch(r'\[\w+\]', text):
        return False
    # Excluir si no contiene ninguna letra (ej: "...", "!!!")
    if not re.search(r'[a-zA-Z]', text):
        return False
    return True

def extract_text_from_file(filepath):
    """Extrae todas las cadenas de texto candidatas a traducción de un archivo."""
    found_texts = []
    with open(filepath, 'r', encoding='utf-8') as f:
        in_python_block = False
        for line_num, line in enumerate(f, 1):
            stripped_line = line.strip()

            # Omitir comentarios y líneas vacías
            if not stripped_line or stripped_line.startswith('#'):
                continue

            # Manejo básico de bloques `python:`
            if stripped_line.startswith('python:'):
                in_python_block = True
                continue
            if in_python_block:
                if stripped_line == '' or line.startswith('    '):
                    continue
                else:
                    in_python_block = False

            # Comprobar si la línea comienza con una palabra clave no traducible
            first_word = stripped_line.split(' ')[0]
            if first_word.lower() in NON_TRANSLATABLE_KEYWORDS:
                continue

            # Intentar encontrar coincidencias con las regex de diálogo o narrador
            match = DIALOGUE_REGEX.search(stripped_line) or NARRATOR_REGEX.search(stripped_line)

            if match:
                # El texto es siempre el último grupo capturado por la regex
                original_text = match.groups()[-1]

                # Limpiar el texto de secuencias de escape de Ren'Py comunes
                original_text = original_text.replace('\\"', '"').replace("\\'", "'")

                if is_valid_text(original_text):
                    found_texts.append({
                        "original": original_text,
                        "file": str(filepath),
                        "line": line_num
                    })
    return found_texts

def extract_mode(game_folder, output_csv):
    """
    Modo de extracción: busca textos en los archivos .rpy y los guarda en un CSV.
    """
    print(f"Buscando archivos .rpy en: '{game_folder}'...")
    rpy_files = find_rpy_files(game_folder)
    if not rpy_files:
        print("Error: No se encontraron archivos .rpy en la carpeta 'game'. Asegúrate de ejecutar el script en el directorio raíz del juego.")
        return

    print(f"Se encontraron {len(rpy_files)} archivos .rpy. Extrayendo textos...")

    all_texts = []
    seen_originals = set()

    for rpy_file in rpy_files:
        texts_in_file = extract_text_from_file(rpy_file)
        for text_info in texts_in_file:
            # Añadir solo si el texto no ha sido visto antes para evitar duplicados
            if text_info["original"] not in seen_originals:
                all_texts.append(text_info)
                seen_originals.add(text_info["original"])

    print(f"Se encontraron {len(all_texts)} cadenas de texto únicas para traducir.")

    if not all_texts:
        print("No se encontraron textos para traducir. Si crees que esto es un error, puede que la lógica de extracción necesite ajustes.")
        return

    print(f"Creando archivo CSV en '{output_csv}'...")
    try:
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            # Escribir la cabecera
            writer.writerow(["id", "original", "translation", "source_file", "line_number"])
            # Escribir los datos
            for i, text_info in enumerate(all_texts):
                placeholder_id = f"ID_{i:05d}"
                writer.writerow([
                    placeholder_id,
                    text_info["original"],
                    "",  # Columna de traducción vacía
                    text_info["file"],
                    text_info["line"]
                ])
        print(f"¡Éxito! El archivo '{output_csv}' ha sido creado. Ahora puedes abrirlo y añadir tus traducciones en la columna 'translation'.")
    except IOError as e:
        print(f"Error al escribir el archivo CSV: {e}")


def apply_mode(input_csv, create_backups=True):
    """
    Modo de aplicación: Lee el CSV traducido y sustituye los textos en los archivos .rpy.
    """
    print(f"Leyendo traducciones desde '{input_csv}'...")
    try:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            translations = [row for row in reader if row.get("translation", "").strip()]
    except FileNotFoundError:
        print(f"Error: El archivo '{input_csv}' no existe.")
        return
    except Exception as e:
        print(f"Error al leer el archivo CSV: {e}")
        return

    if not translations:
        print("No se encontraron traducciones en el archivo CSV. Asegúrate de rellenar la columna 'translation'.")
        return

    print(f"Se encontraron {len(translations)} traducciones para aplicar.")

    # Agrupar traducciones por archivo para procesar cada archivo una sola vez
    file_map = {}
    for t in translations:
        if t["source_file"] not in file_map:
            file_map[t["source_file"]] = []
        # Guardamos la línea como entero para poder ordenarlas
        t['line_number'] = int(t['line_number'])
        file_map[t["source_file"]].append(t)

    total_files = len(file_map)
    processed_files = 0

    for filepath, trans_list in file_map.items():
        processed_files += 1
        print(f"Procesando archivo ({processed_files}/{total_files}): {filepath}...")

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Ordenar las traducciones por número de línea en orden descendente
            # para evitar problemas si hay múltiples reemplazos en la misma línea
            trans_list.sort(key=lambda x: x['line_number'], reverse=True)

            modified_count = 0
            for trans in trans_list:
                line_idx = trans["line_number"] - 1
                if 0 <= line_idx < len(lines):
                    original_line = lines[line_idx]
                    original_text = trans["original"]
                    translated_text = trans["translation"]

                    # Escapar comillas dobles en la traducción para que sea una cadena válida en Ren'Py
                    translated_text = translated_text.replace('"', '\\"')

                    # Reemplazar el texto original por el traducido
                    # Nos aseguramos de reemplazar la cadena exacta entre comillas
                    old_string = f'"{original_text}"'
                    new_string = f'"{translated_text}"'

                    if old_string in original_line:
                        lines[line_idx] = original_line.replace(old_string, new_string, 1)
                        modified_count += 1
                    else:
                        print(f"  [ADVERTENCIA] No se encontró el texto original en la línea {line_idx+1} de '{filepath}'. Puede que el archivo haya cambiado.")

            if modified_count > 0:
                if create_backups:
                    backup_path = f"{filepath}.bak"
                    print(f"  Creando copia de seguridad en '{backup_path}'")
                    os.rename(filepath, backup_path)

                print(f"  Aplicando {modified_count} traducciones...")
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.writelines(lines)

        except FileNotFoundError:
            print(f"  [ERROR] El archivo '{filepath}' no se encontró. Saltando...")
        except Exception as e:
            print(f"  [ERROR] Ocurrió un error al procesar '{filepath}': {e}")

    print("\n¡Proceso de traducción completado!")


def main():
    parser = argparse.ArgumentParser(
        description="Una herramienta para extraer y aplicar traducciones a juegos de Ren'Py.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "mode",
        choices=["extract", "apply"],
        help="El modo de operación:\n"
             "extract - Extrae el texto de los archivos .rpy a un archivo CSV.\n"
             "apply   - Aplica las traducciones de un archivo CSV a los archivos .rpy."
    )
    parser.add_argument(
        "--game",
        default="game",
        help="La ruta a la carpeta 'game' del proyecto. Por defecto es 'game'."
    )
    parser.add_argument(
        "--csv",
        default="translations.csv",
        help="El nombre del archivo CSV para leer o escribir. Por defecto es 'translations.csv'."
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Desactiva la creación de copias de seguridad (.bak) al aplicar traducciones."
    )

    args = parser.parse_args()

    if args.mode == "extract":
        if not os.path.isdir(args.game):
            print(f"Error: La carpeta '{args.game}' no existe. Asegúrate de estar en el directorio raíz de tu juego.")
            return
        extract_mode(args.game, args.csv)
    elif args.mode == "apply":
        apply_mode(args.csv, not args.no_backup)

if __name__ == "__main__":
    main()
