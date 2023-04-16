import sqlite3
import os
import glob
from tkinter import *
from tkinter import filedialog
from datetime import datetime
import threading
from tkinter import ttk
import time
import re
import psutil
import string
import ctypes
import sqlite3
from tkinter import messagebox

scanned_files = []
db_lock = threading.Lock()

def get_drive_serial_number(drive_letter):
    # Drive letter should be something like 'C:'
    if not drive_letter or len(drive_letter) != 2 or drive_letter[1] != ':' or drive_letter[0] not in string.ascii_uppercase:
        return None

    drive = drive_letter + '\\'
    serial_number = ctypes.c_ulong(0)
    max_component_length = ctypes.c_ulong(0)
    file_system_flags = ctypes.c_ulong(0)

    result = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive),
        None,
        0,
        ctypes.pointer(serial_number),
        ctypes.pointer(max_component_length),
        ctypes.pointer(file_system_flags),
        None,
        0
    )

    if result == 0:
        return None

    return serial_number.value

def print_database_records():
    with db_lock:
        conn = sqlite3.connect('search_tool.db', timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files")
        records = cursor.fetchall()
        conn.close()

    for record in records:
        print(record)

def get_drive_info(drive_letter):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    volume_name_buf = ctypes.create_unicode_buffer(1024)
    serial_number = ctypes.c_uint32()
    
    success = kernel32.GetVolumeInformationW(drive_letter + "\\", volume_name_buf, 1024, ctypes.byref(serial_number), None, None, None, 0)

    if success == 0:
        raise Exception(f"Failed to get drive info: Drive '{drive_letter}' not found")

    return volume_name_buf.value, serial_number.value

def get_volume_label(drive_letter):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    buf = ctypes.create_unicode_buffer(1024)
    n = kernel32.GetVolumeInformationW(drive_letter + "\\", buf, 1024, None, None, None, None, 0)

    if n == 0:
        raise Exception(f"Failed to get volume label: Drive '{drive_letter}' not found")

    return buf.value

def get_hard_disk_label(drive_letter):
    try:
        return get_volume_label(drive_letter)
    except Exception:
        return ''

def search_database(keyword, search_only_folder):
    formatted_results = []

    with db_lock:
        try:
            conn = sqlite3.connect('search_tool.db', timeout=10)
            cursor = conn.cursor()

            if search_only_folder:
                search_drive = os.path.splitdrive(folder_path_var.get())[0]
                cursor.execute("SELECT filepath, filename, drive_label, drive_serial_number FROM files WHERE filename LIKE ? AND drive_serial_number = ?",
                               ('%' + keyword + '%', get_drive_serial_number(search_drive)))
            else:
                cursor.execute("SELECT * FROM files WHERE filename LIKE ?", ('%' + keyword + '%',))

            results = cursor.fetchall()
            conn.close()
        except sqlite3.OperationalError as e:
            print(f"Error: {e}")
            time.sleep(5)
            return []

    for result in results:
        filepath, filename, drive_label, drive_serial_number = result
        drive_letter = os.path.splitdrive(filepath)[0]
        hard_disk_serial_number = get_drive_serial_number(drive_letter)

        if hard_disk_serial_number == drive_serial_number:
            formatted_results.append(f"[DB] {filepath}")
        else:
            if drive_label:
                formatted_results.append(f"[DB] - {drive_label} - {filepath}")
            else:
                formatted_results.append(f"[DB] - - {filepath}")

    return formatted_results
         
def search_path(keyword, path, search_only_folder):
    global scanned_files, num_scanned_files
    scanned_files = []
    num_scanned = 0

    results = []
    file_data_list = []
    for dirpath, _, files in os.walk(path):
        if stop_search:
            break
        current_folder.set(f"{dirpath}")
        num_scanned_files.set(f"{num_scanned}")
        root.update_idletasks()
        for file in files:
            filepath = os.path.join(dirpath, file)
            drive_letter = os.path.splitdrive(filepath)[0]
            hard_disk_serial_number = get_drive_serial_number(drive_letter)

            if hard_disk_serial_number is not None:
                drive_serial_number = hard_disk_serial_number

            # Updated file_data tuple
            drive_label = get_hard_disk_label(drive_letter)
            file_data = (filepath, file, drive_label, drive_serial_number)
            file_data_list.append(file_data)

            if keyword in file:
                scanned_files.append(file_data)
                results.append(filepath)

                # Insert the result into the listbox
                result_list.insert(END, f"[HD] {filepath}")

            num_scanned += 1

    while True:
        try:
            with db_lock:
                conn = sqlite3.connect('search_tool.db', timeout=10)
                cursor = conn.cursor()
                cursor.executemany("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)", file_data_list)
                conn.commit()
                conn.close()
                break
        except sqlite3.OperationalError:
            time.sleep(5)

    return results

def stop():
    global stop_search, scanned_files
    stop_search = True

    # Update the SQL database with the scanned files
    while True:
        try:
            with db_lock:
                conn = sqlite3.connect('search_tool.db', timeout=10)
                cursor = conn.cursor()
                for file_data in scanned_files:
                    cursor.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)", file_data)
                conn.commit()
                conn.close()
                break
        except sqlite3.OperationalError:
            time.sleep(5)

    # Clear the scanned_files list
    scanned_files = []

def create_database():
    while True:
        try:
            conn = sqlite3.connect('search_tool.db', timeout=10)
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS files
                              (filepath TEXT, filename TEXT, drive_label TEXT, drive_serial_number INTEGER)''')
            cursor.execute('''CREATE INDEX IF NOT EXISTS filename_index ON files (filename)''')
            conn.commit()
            conn.close()
            break
        except sqlite3.OperationalError:
            time.sleep(5)

def update_database(path):
    while True:
        try:
            conn = sqlite3.connect('search_tool.db', timeout=10)
            cursor = conn.cursor()
            cursor.execute('BEGIN TRANSACTION')
            cursor.execute('DELETE FROM files')
            file_data_list = []
            for root, _, files in os.walk(path):
                for file in files:
                    filepath = os.path.join(root, file)
                    drive_letter = os.path.splitdrive(filepath)[0]
                    drive_label = get_hard_disk_label(drive_letter)  # Update this line
                    drive_serial_number = get_drive_serial_number(drive_letter)  # Add this line

                    file_data = (filepath, file, drive_label, drive_serial_number)  # Add drive_serial_number
                    file_data_list.append(file_data)
            cursor.executemany("INSERT INTO files VALUES (?, ?, ?, ?)", file_data_list)  # Update the number of placeholders
            cursor.execute('COMMIT')
            conn.close()
            break
        except sqlite3.OperationalError:
            time.sleep(5)

def open_explorer(filepath):
    # Remove the prefix '[HD]' or '[DB]' and strip any leading or trailing spaces
    filepath = filepath[4:].strip()

    # Check if the drive is disconnected
    if filepath.startswith("-"):
        return

    # Split the file path string into a list
    filepath_list = filepath.split(',')

    # Extract the actual file path from the list
    actual_filepath = filepath_list[0].strip()

    # Remove any leading or trailing parentheses, single quotes, or double quotes
    actual_filepath = actual_filepath.strip("() '\"")

    normalized_path = os.path.normpath(actual_filepath)
    absolute_path = os.path.abspath(normalized_path)

    print(f"Absolute path: {absolute_path}")

    os.startfile(os.path.dirname(absolute_path))

def search():
    global stop_search
    stop_search = False
    search_thread = threading.Thread(target=perform_search)
    search_thread.start()

def perform_search():
    keyword = keyword_var.get()
    
    # Get the state of the checkboxes
    search_only_folder = search_only_folder_var.get()
    search_without_db = search_without_db_var.get()
    search_db_only = search_db_only_var.get()

    if not search_db_only:
        # Update the status label to show searching on the hard drive
        current_folder.set("Searching on the hard drive...")
        root.update_idletasks()
        harddrive_results = search_path(keyword, folder_path, search_only_folder)
        
        # Insert the results from the hard drive
        for result in harddrive_results:
            result_list.insert(END, f"[HD] {result}")

    if not search_without_db:
        # Update the status label to show searching in the database
        current_folder.set("Searching in the database...")
        root.update_idletasks()
        # Pass the search_only_folder flag to the search_database function
        database_results = search_database(keyword, search_only_folder)
        
        # Clear the result_list and insert the results from the database
        result_list.delete(0, END)
        for result in database_results:
            result_list.insert(END, result)

    current_folder.set("Search completed.")

def browse_folder():
    global folder_path
    folder_path = filedialog.askdirectory(initialdir="C:/")
    folder_path_var.set(folder_path)

def check_database_integrity(database_file):
    conn = sqlite3.connect(database_file)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA integrity_check;")
    result = cursor.fetchone()
    
    conn.close()
    
    if result[0] == 'ok':
        return True
    else:
        return False

def optimize_database():
    database_file = 'search_tool.db'

    if not check_database_integrity(database_file):
        messagebox.showerror("Integrity Check", "Database integrity check failed. Please fix the issues before optimizing.")
        return

    with sqlite3.connect(database_file) as connection:
        cursor = connection.cursor()

        # Create chunks table if it doesn't exist
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id INTEGER PRIMARY KEY,
            data BLOB
        );
        """)
        connection.commit()

        # Remove duplicate chunks
        cursor.execute("DELETE FROM chunks WHERE rowid NOT IN (SELECT MIN(rowid) FROM chunks GROUP BY chunk_id);")
        connection.commit()

        # Shrink the database file
        cursor.execute("VACUUM;")
        connection.commit()

    messagebox.showinfo("Optimize DB", "Database optimization completed.")

def handle_checkboxes():
    if search_db_only_var.get():
        search_without_db_check.configure(state=DISABLED)
    else:
        search_without_db_check.configure(state=NORMAL)

    if search_without_db_var.get():
        search_db_only_check.configure(state=DISABLED)
    else:
        search_db_only_check.configure(state=NORMAL)

create_database()


if __name__ == "__main__":
    create_database()
    root = Tk()
    
    root.title("Search Tool")

    keyword_var = StringVar()
    folder_path_var = StringVar()
    current_folder = StringVar()
    folder_path = ''
    stop_search = False

    search_only_folder_var = IntVar()
    search_without_db_var = IntVar()
    search_db_only_var = IntVar()

    main_frame = ttk.Frame(root)
    main_frame.grid(row=0, column=0, sticky="nsew")

    search_options_frame = ttk.LabelFrame(main_frame, text="Search Options")
    search_options_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

    result_frame = ttk.LabelFrame(main_frame, text="Results")
    result_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    database_management_frame = ttk.LabelFrame(main_frame, text="Database Management")
    database_management_frame.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")

    # Search options frame
    keyword_label = ttk.Label(search_options_frame, text="Keyword:")
    keyword_label.grid(row=0, column=0)
    keyword_entry = ttk.Entry(search_options_frame, textvariable=keyword_var)
    keyword_entry.grid(row=0, column=1)

    folder_label = ttk.Label(search_options_frame, text="Folder:")
    folder_label.grid(row=1, column=0)
    folder_entry = ttk.Entry(search_options_frame, textvariable=folder_path_var)
    folder_entry.grid(row=1, column=1)
    folder_button = ttk.Button(search_options_frame, text="Browse", command=browse_folder)
    folder_button.grid(row=1, column=2)

    search_button = ttk.Button(search_options_frame, text="Search", command=search)
    search_button.grid(row=2, column=0)
    stop_button = ttk.Button(search_options_frame, text="Stop", command=stop)
    stop_button.grid(row=2, column=1)

    status_label = ttk.Label(search_options_frame, text="Current folder:")
    status_label.grid(row=2, column=2)
    status_value = ttk.Label(search_options_frame, textvariable=current_folder, width=50)
    status_value.grid(row=2, column=3)

    search_only_folder_check = ttk.Checkbutton(search_options_frame, text="Search only defined folder/drive", variable=search_only_folder_var)
    search_only_folder_check.grid(row=3, column=0)

    search_without_db_check = ttk.Checkbutton(search_options_frame, text="Search without database", variable=search_without_db_var, command=handle_checkboxes)
    search_without_db_check.grid(row=3, column=1)

    search_db_only_check = ttk.Checkbutton(search_options_frame, text="Search database only", variable=search_db_only_var, command=handle_checkboxes)
    search_db_only_check.grid(row=3, column=2)

    # Result frame
    result_list = Listbox(result_frame, width=100, height=20)
    result_list.grid(row=0, column=0, columnspan=4, sticky='nsew')
    result_list.bind('<Double-1>', lambda event: open_explorer(result_list.get(result_list.curselection())))

    scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=result_list.yview)
    scrollbar.grid(row=0, column=4, sticky="ns")
    result_list.config(yscrollcommand=scrollbar.set)

    result_list.config(yscrollcommand=scrollbar.set)

    scanned_files_label = ttk.Label(result_frame, text="Scanned files:")
    scanned_files_label.grid(row=1, column=2)

    num_scanned_files = StringVar()
    num_scanned_files_label = ttk.Label(result_frame, textvariable=num_scanned_files, width=20)
    num_scanned_files_label.grid(row=1, column=3)

    # Database management frame
    print_db_button = ttk.Button(database_management_frame, text="Print DB", command=print_database_records)
    print_db_button.grid(row=0, column=0)

    optimize_db_button = ttk.Button(database_management_frame, text="Optimize DB", command=check_database_integrity)
    optimize_db_button.grid(row=0, column=1)

    # Configure the grid
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    main_frame.grid_columnconfigure(0, weight=1)
    main_frame.grid_rowconfigure(0, weight=1)
    main_frame.grid_rowconfigure(1, weight=1)
    main_frame.grid_rowconfigure(2, weight=1)

    search_options_frame.grid_columnconfigure(1, weight=1)
    result_frame.grid_columnconfigure(3, weight=1)
    result_frame.grid_rowconfigure(0, weight=1)

    root.mainloop()
