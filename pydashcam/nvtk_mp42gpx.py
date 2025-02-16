#!/usr/bin/env python
# Author: Sergei Franco (sergei at sergei.nz)
# License: GPL3
# Warranty: NONE! Use at your own risk!
""" This script will crudely extract embedded GPS data from Novatek generated MP4/TS files. """

import os
import sys
import argparse
import glob
import struct
import math
import time


def check_out_file(out_file, force):
    """ checks if the out_file exists and bomb-out if 'force' flag is not set """
    if os.path.isfile(out_file) and not force:
        print("Warning: specified out file '%s' exists, specify '-f' to overwrite it!" % out_file)
        return False
    return True


def check_in_file(in_file):
    """ checks input file(s) and deal with globs """
    in_files = []
    for in_f in in_file:
        # glob needed if for some reason quoted glob is passed,
        # or script is run on the most popular proprietary and inferior OS
        for in_f1 in glob.glob(in_f):
            if os.path.isdir(in_f1):
                print("Directory '%s' specified as input, listing..." % in_f1)
                for in_f2 in os.listdir(in_f1):
                    in_f3 = os.path.join(in_f1, in_f2)
                    if os.path.isfile(in_f3):
                        print("Queueing file '%s' for processing..." % in_f3)
                        in_files.append(in_f3)
            elif os.path.isfile(in_f1):
                print("Queueing file '%s' for processing..." % in_f1)
                in_files.append(in_f1)
            else:
                # Catch all for typos...
                print("Skipping invalid input '%s'..." % in_f1)
    if not in_files:
        print("No input files found in %s." % in_file)
        sys.exit(1)
    return in_files


def get_args():
    """ parsing arguments """
    parser = argparse.ArgumentParser(
        description=('This script will attempt to extract GPS data'
                     'from a Novatek MP4/MOV/TS file and output it in a GPX format.'))
    parser.add_argument('-i', metavar='input', nargs='+',
                        help='input file(s), globs (eg: *) or directory(ies).')
    parser.add_argument('-o', metavar='output', nargs=1,
                        help='output file (single).')
    parser.add_argument('-f', action='store_true',
                        help='overwrite output file if exists.')
    parser.add_argument('-d', action='store_true',
                        help=('deobfuscates coordinates, '
                              'if the file only works with JMSPlayer use this flag.'))
    parser.add_argument('-e', action='store_true',
                        help=('exclude outliers. '
                              'Removes impossible coordinates due to errors in the GPS data.'))
    parser.add_argument('-m', action='store_true',
                        help=('multiple output files (default creates a single output file). '
                              'Note: files will be named after originals.'))
    parser.add_argument('-s', metavar='sorting', nargs='?', default='d',
                        help=('Specify on what to sort by. '
                              'The \'-s f\' will sort the output by the file name. '
                              'The \'-s d\' will sort the output by the GPS date (default). '
                              'The \'-s n\' will not sort the output.'))
    try:
        args = parser.parse_args(sys.argv[1:])
        force = args.f

        sort_by = args.s
        sort_flags = {
            'd': 'Sort coordinates by the GPS Date',
            'f': 'Sort coordinates by the input file name.',
            'n': 'Do not sort coordinates.',
        }
        if sort_by not in sort_flags.keys():
            print("ERROR: unsupported sort flag '%s' (supported flags: %s)."
                  % (sort_by, sort_flags))
            parser.print_help()
            sys.exit(1)
        else:
            print("Selected coordinate sort method: %s." % sort_flags[sort_by])

        if args.o and args.m:
            print(("Warning: '-m' is set: output file name will be derived from input file name,"
                   "'-o' will be ignored"))
        if not args.m:
            out_file = args.o[0]
            if not check_out_file(out_file, force):
                sys.exit(1)
        else:
            out_file = None

        multiple = args.m
        deobfuscate = args.d
        del_outliers = args.e
        in_file = check_in_file(args.i)

    except TypeError:
        parser.print_help()
        sys.exit(1)
    return in_file, out_file, force, multiple, deobfuscate, sort_by, del_outliers


def fix_time(datetime):
    """ time format manipulation -> YYYY-MM-DDTHH:mm:SSZ """
    date = ("%d-%02d-%02dT%02d:%02d:%02dZ"
            % ((datetime['Year'] + 2000),
               int(datetime['Month']),
               int(datetime['Day']),
               int(datetime['Hour']),
               int(datetime['Minute']),
               int(datetime['Second'])))
    return date


def fix_coordinates(hemisphere, coordinate, deobfuscate=False):
    """ converts coordinate format from DDDmm.mmmm to signed float (unless obfuscated)"""
    if not deobfuscate:
        minutes = coordinate % 100.0
        degrees = coordinate - minutes
        coordinate = degrees / 100.0 + (minutes / 60.0)
    if hemisphere in ['S', 'W']:
        return -1 * float(coordinate)
    return float(coordinate)


def fix_speed(speed):
    """ simple knot to m/s conversion; 1 knot = 0.514444 m/s """
    return speed * float(0.514444)


def get_atom_info(eight_bytes):
    """ reads atom type from the given 4Bytes with some minimal sanity checks """
    try:
        atom_size, atom_type = struct.unpack('>I4s', eight_bytes)
    except struct.error:
        return 0, ''
    try:
        a_t = atom_type.decode()
    except UnicodeDecodeError:
        a_t = 'UNKNOWN'
    return int(atom_size), a_t


def get_gps_atom_info(eight_bytes):
    """ get atom position and size from the given 8Byte header """
    atom_pos, atom_size = struct.unpack('>II', eight_bytes)
    return int(atom_pos), int(atom_size)


def deobfuscate_coord(latitude, longitude):
    """ Deobfuscated GPS coordinates.
    Chinese manufacturers play silly and futile games with their data structures.
    It is utterly pointless as one can always decompile their crappy players.
    https://sergei.nz/dealing-with-data-obfuscation-in-some-chinese-dash-cameras/
    """
    latitude = (latitude - 187.98217) / 3
    longitude = (longitude - 2199.19876) * 0.5
    return latitude, longitude


def get_gps_offset(data):
    """ finds gps payload position within the data backet """
    # start at the end with 20 bytes allowed for trailing data
    pointer = len(data) - 20
    beginning = 0
    offset = beginning
    while pointer > beginning:
        active, lon_hemi, lat_hemi = struct.unpack_from('<sss', data, pointer)
        try:
            active = active.decode()
            lon_hemi = lon_hemi.decode()
            lat_hemi = lat_hemi.decode()
        except UnicodeDecodeError:
            pass
        if active == 'A' and lon_hemi in ['N', 'S'] and lat_hemi in ['E', 'W']:
            # the A{N,S}{E,W} is 24 bytes away from the beginning of the data packet
            offset = pointer - 24
            break
        pointer -= 1
    else:
        return -1
    return offset


def convert_to_epoch(datetime):
    """ converts the 'datetime' to the epoch time """
    # 2021-01-09T21:16:27Z -> %Y-%m-%dT%H:%M:%SZ
    # Assuming the timezone always Z.
    time_struct = time.strptime(datetime[:-1] + 'UTC', "%Y-%m-%dT%H:%M:%S%Z")
    # Warning: the 'epoch' will not be in the UTC, due to limitation of the mktime
    # this is is not important as the epoch is only used for sorting and it will
    # work as long as it is internally consistent.
    # I decided to stick to time (as opposed to datetime) for compatibility reasons
    # as datetime might not be available on all systems.
    epoch = int(time.mktime(time_struct))
    return epoch


def decode_azdome(gps, data):
    """ decodes azdome specific payload """
    payload = []
    # really crude XOR decryptor
    for index in range(len(data)):
        payload.append(chr(struct.unpack_from('>B', data, index)[0] ^ 0xAA))
    try:
        gps['DT']['Year'] = ''.join(payload[14:18])
        gps['DT']['Month'] = ''.join(payload[18:20])
        gps['DT']['Day'] = ''.join(payload[20:22])
        gps['DT']['Hour'] = ''.join(payload[22:24])
        gps['DT']['Minute'] = ''.join(payload[24:26])
        gps['DT']['Second'] = ''.join(payload[26:28])
        gps['DT']['DT'] = "%s-%s-%sT%s:%s:%sZ" % (
            gps['DT']['Year'],
            gps['DT']['Month'],
            gps['DT']['Day'],
            gps['DT']['Hour'],
            gps['DT']['Minute'],
            gps['DT']['Second'])
        gps['Loc']['Lat']['Raw'] = float(''.join(payload[45:53])) / 10000
        gps['Loc']['Lat']['Hemi'] = payload[44]
        gps['Loc']['Lon']['Raw'] = float(''.join(payload[54:62])) / 1000
        gps['Loc']['Lon']['Hemi'] = payload[53]
        gps['Loc']['Lat']['Float'] = fix_coordinates(
            gps['Loc']['Lat']['Hemi'], gps['Loc']['Lat']['Raw'])
        gps['Loc']['Lon']['Float'] = fix_coordinates(
            gps['Loc']['Lon']['Hemi'], gps['Loc']['Lon']['Raw'])
        # speed is not as accurate as it could be, only -1/+0 km/h.
        gps['Loc']['Speed'] = float(''.join(payload[69:71])) / 3.6
        # no bearing data
        gps['Loc']['Bearing'] = 0
    except ValueError:
        # skipping "bad" payload
        return None
    return gps


def get_gps_data(data, deobfuscate):
    """ gets gps data from a trimmed packet payload """
    gps = {
        'Epoch': None,
        'DT': {
            'Year': None,
            'Month': None,
            'Day': None,
            'Hour': None,
            'Minute': None,
            'Second': None,
            'DT': None
        },
        'Loc': {
            'Lat': {
                'Raw': None,
                'Hemi': None,
                'Float': None,
            },
            'Lon': {
                'Raw': None,
                'Hemi': None,
                'Float': None,
            },
            'Speed': None,
            'Bearing': None,
        },
    }
    offset = get_gps_offset(data)
    # in python3 data[0] is an int and in python2 data[0] is a str...
    # to make the script version agnostic one uses struct.upack as char
    azdome = False
    if struct.unpack_from('>c', data)[0] in [b'\x05', b'\xF0']:
        out = decode_azdome(gps, data)
        if out:
            gps = out
            azdome = True

    if not azdome and offset >= 0:

        # Added Bearing as per RetiredTechie contribuition:
        # http://retiredtechie.fitchfamily.org/2018/05/13/dashcam-openstreetmap-mapping/

        gps['DT']['Hour'], gps['DT']['Minute'], gps['DT']['Second'] = struct.unpack_from(
            '<III', data, offset)
        offset = offset + (3 * 4)
        gps['DT']['Year'], gps['DT']['Month'], gps['DT']['Day'] = struct.unpack_from(
            '<III', data, offset)
        offset = offset + (3 * 4)
        active, gps['Loc']['Lat']['Hemi'], gps['Loc']['Lon']['Hemi'] = struct.unpack_from(
            '<sss', data, offset)
        offset = offset + 4  # 3bytes for '<sss' and 1byte for an unkown char
        gps['Loc']['Lat']['Raw'], gps['Loc']['Lon']['Raw'] = struct.unpack_from(
            '<ff', data, offset)
        offset = offset + (2 * 4)
        gps['Loc']['Speed'], gps['Loc']['Bearing'] = struct.unpack_from(
            '<ff', data, offset)

        try:
            active = active.decode()
            gps['Loc']['Lat']['Hemi'] = gps['Loc']['Lat']['Hemi'].decode()
            gps['Loc']['Lon']['Hemi'] = gps['Loc']['Lon']['Hemi'].decode()

        except UnicodeDecodeError as error:
            print("Skipping: garbage data. Error: %s." % str(error))
            return None

        if deobfuscate:
            gps['Loc']['Lat']['Raw'], gps['Loc']['Lon']['Raw'] = deobfuscate_coord(
                gps['Loc']['Lat']['Raw'], gps['Loc']['Lon']['Raw'])

        gps['Loc']['Lat']['Float'] = fix_coordinates(
            gps['Loc']['Lat']['Hemi'], gps['Loc']['Lat']['Raw'], deobfuscate)
        gps['Loc']['Lon']['Float'] = fix_coordinates(
            gps['Loc']['Lon']['Hemi'], gps['Loc']['Lon']['Raw'], deobfuscate)
        gps['Loc']['Speed'] = fix_speed(gps['Loc']['Speed'])
        gps['DT']['DT'] = fix_time(gps['DT'])
    else:
        return None
    try:
        gps['Epoch'] = convert_to_epoch(gps['DT']['DT'])
    except ValueError:
        return None

    return gps


def get_gps_atom(gps_atom_info, in_fh, deobfuscate):
    """ gets payload from a 'free' atom type and checks if it is there is a 'GPS ' payload """
    atom_pos, atom_size = gps_atom_info
    if atom_size == 0 or atom_pos == 0:
        print("Error! skipping atom at %x atom size:%d!" % (int(atom_pos), atom_size))
        return None
    in_fh.seek(atom_pos)
    data = in_fh.read(atom_size)
    expected_type = 'free'
    expected_magic = 'GPS '
    atom_size1, atom_type, magic = struct.unpack_from('>I4s4s', data)
    try:
        atom_type = atom_type.decode()
        magic = magic.decode()
        # sanity:
        if atom_size != atom_size1 or atom_type != expected_type or magic != expected_magic:
            print("Error! skipping atom at %x"
                  "(expected size:%d, actual size:%d, expected type:%s, "
                  "actual type:%s, expected magic:%s, actual maigc:%s)!"
                  % (int(atom_pos), atom_size, atom_size1,
                     expected_type, atom_type, expected_magic, magic))
            return None
    except UnicodeDecodeError as error:
        print("Skipping: garbage atom type or magic. Error: %s." % str(error))
        return None

    out = get_gps_data(data[12:], deobfuscate)
    return out


def generate_gpx(gps_data, out_file):
    """ generates GPX formatted data from given GPS data """
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.0"\n'
           '\tcreator="Sergei\'s Novatek MP4 GPS parser"\n'
           '\txmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
           '\txmlns="http://www.topografix.com/GPX/1/0"\n'
           '\txsi:schemaLocation="http://www.topografix.com/GPX/1/0 '
           'http://www.topografix.com/GPX/1/0/gpx.xsd">\n')
    gpx += "\t<name>%s</name>\n" % out_file
    gpx += '\t<url>sergei.nz</url>\n'
    gpx += "\t<trk><name>%s</name><trkseg>\n" % out_file
    for gps in gps_data:
        if gps:
            gpx += ("\t\t<trkpt lat=\"%f\" lon=\"%f\"><time>%s</time>"
                    % (gps['Loc']['Lat']['Float'],
                       gps['Loc']['Lon']['Float'],
                       gps['DT']['DT']))

            gpx += ("<speed>%f</speed><course>%f</course></trkpt>\n"
                    % (gps['Loc']['Speed'],
                       gps['Loc']['Bearing']))
    gpx += ('\t</trkseg></trk>\n'
            '</gpx>\n')
    return gpx


def parse_ts(in_fh, deobfuscate):
    """ crude TS parser """
    gps_data = []
    is_ts = False
    # Testing for 'G' sync header every 188 bytes 3 times
    # to make sure we have TS stream here.
    # It is possible to drop this test entirely,
    # as subsequent tests will catch out garbage data
    in_fh.seek(0, 0)
    test_sync_1 = in_fh.read(1)
    in_fh.seek(188, 0)
    test_sync_2 = in_fh.read(1)
    in_fh.seek(376, 0)
    test_sync_3 = in_fh.read(1)
    if test_sync_1 == test_sync_2 == test_sync_3 == b'G':
        is_ts = True
        in_fh.seek(0, 0)
        position = 0
        partial = ''
        while True:
            header = in_fh.read(4)
            if header[1:3] in [b'C\x00', b'\x03\x00']:
                frame = in_fh.read(184)
                # 0x000001 = Beginning of the PES header, 0xBF = Private Stream 2,
                # navigational data;
                # see http://dvd.sourceforge.net/dvdinfo/pes-hdr.html
                # this whole nonsense with partial variable is because of malicious
                # and purposeful data obfuscation on B4K cameras.
                if frame[:4] == b'\x00\x00\x01\xbf':
                    data = get_gps_data(frame, deobfuscate)
                    if data:
                        gps_data.append(data)
                    else:
                        partial = frame[-14:]
                else:
                    if partial:
                        # note due to weirdness of python3+ if I just
                        # struct.unpack('<B', frame[0]) it blows up
                        # while in python2.7 it works.
                        # for some silly reason frame[0] is an int in python3+.
                        jump = struct.unpack_from('<B', frame[:1])[0] + 1
                        data = get_gps_data(partial + frame[jump:], deobfuscate)
                        gps_data.append(data)
                        partial = ''
            position += 188
            in_fh.seek(position, 0)
            if not header:
                break
    return gps_data, is_ts


def parse_moov(in_fh, deobfuscate):
    """ crude MP4/MOV (moov) parser """
    gps_data = []
    offset = 0
    is_moov = False
    while True:
        atom_size, atom_type = get_atom_info(in_fh.read(8))
        if atom_size == 0:
            break

        if atom_type == 'moov':
            print("\tFound the 'moov' atom.")
            is_moov = True
            sub_offset = offset + 8
            while sub_offset < (offset + atom_size):
                sub_atom_size, sub_atom_type = get_atom_info(in_fh.read(8))

                if str(sub_atom_type) == 'gps ':
                    print("\tFound the gps chunk descriptor atom.")
                    gps_offset = 16 + sub_offset  # +16 = skip headers
                    in_fh.seek(gps_offset, 0)
                    while gps_offset < (sub_offset + sub_atom_size):
                        data = get_gps_atom(get_gps_atom_info(in_fh.read(8)), in_fh, deobfuscate)
                        gps_data.append(data)
                        gps_offset += 8
                        in_fh.seek(gps_offset, 0)

                sub_offset += sub_atom_size
                in_fh.seek(sub_offset, 0)

        offset += atom_size
        in_fh.seek(offset, 0)
    return gps_data, is_moov


def calculate_speed(coord_dt1, coord_dt2):
    """ calculates speed based two sets of coordinates/datetimes """
    # https://en.wikipedia.org/wiki/Haversine_formula
    lat1, lon1, dt1 = coord_dt1
    lat2, lon2, dt2 = coord_dt2
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)
    earth_r = 6.3781E6  # earth radius meters
    hav_lat = (1 - math.cos(lat2 - lat1)) / 2
    hav_lon = (1 - math.cos(lon2 - lon1)) / 2
    hav_h = hav_lat + math.cos(lat1) * math.cos(lat2) * hav_lon
    distance = 2 * earth_r * math.asin(hav_h ** 0.5)
    try:
        speed = distance / abs(dt2 - dt1)
    except ZeroDivisionError:
        return 0.0
    return speed


def remove_outliers(gps_data):
    """ crudely deletes outliers based on timestamp and coordinate delta """
    if not gps_data:
        return gps_data
    # geting median lat and lon
    lats = []
    lons = []
    epochs = []
    for item in gps_data:
        try:
            lats.append(item['Loc']['Lat']['Float'])
            lons.append(item['Loc']['Lon']['Float'])
            epochs.append(item['Epoch'])
        except TypeError:
            continue
    lats.sort()
    lons.sort()
    epochs.sort()
    # crude midpoint, but fine for the task
    mid_point = (lats[int(len(lats) / 2)],
                 lons[int(len(lons) / 2)],
                 epochs[int(len(epochs) / 2)])
    gps_data_filtered = []
    for data_point in gps_data:
        try:
            point = (data_point['Loc']['Lat']['Float'],
                     data_point['Loc']['Lon']['Float'],
                     data_point['Epoch'])
            speed = calculate_speed(mid_point, point)
        except TypeError:
            continue
        if speed > 1000:
            print("Removed outlier %s (estimated speed: %.2fm/s)." % (point, speed))
        else:
            gps_data_filtered.append(data_point)
    return gps_data_filtered


def process_file(in_file, deobfuscate, del_outliers):
    """ process input file, looks for either MP4 or TS file signatures """
    print("Processing file '%s'..." % in_file)
    gps_data = []
    with open(in_file, "rb") as in_fh:
        gps_data, is_moov = parse_moov(in_fh, deobfuscate)
        if not is_moov:
            print("\tFile %s is not a MP4/MOV file." % in_file)
            gps_data, is_ts = parse_ts(in_fh, deobfuscate)
            if is_ts:
                print("\tFound a TS header.")
            else:
                print("\tFile %s is not a TS file." % in_file)
    out = list(filter(None, gps_data))
    if del_outliers:
        out = remove_outliers(out)
    return out


def write_file(gpx, out_file):
    """ writes given data to a given out put file """
    with open(out_file, "w") as of_h:
        print("Writing data to the output file '%s'." % out_file)
        of_h.write(gpx)


def write_if_gps_data(gps_data, out_file):
    """ checks if the gps_data is there and then generates the gpx """
    if gps_data:
        gpx = generate_gpx(gps_data, out_file)
        print("Found %d GPS data points." % len(gps_data))
        write_file(gpx, out_file)
    else:
        print("GPS data not found in the '%s'!" % out_file)
        return False
    return True


def sort_gps_data_by_dt(gps_data):
    """ sorting by the 'Epoch' key value of the dicts in the gps_data list """
    gps_data.sort(key=lambda item: item['Epoch'])
    return gps_data


def get_data_package(infilepath):
    deobfuscate = None
    del_outliers = None
    gps_data = []
    with open(infilepath, "rb") as in_fh:
        gps_data, is_moov = parse_moov(in_fh, deobfuscate)
        if not is_moov:
            print("\tFile %s is not a MP4/MOV file." % in_file)
            gps_data, is_ts = parse_ts(in_fh, deobfuscate)
            if is_ts:
                print("\tFound a TS header.")
            else:
                print("\tFile %s is not a TS file." % in_file)
    out = list(filter(None, gps_data))
    if del_outliers:
        out = remove_outliers(out)
    return out



def main():
    """ main function """
    in_files, out_file, force, multiple, deobfuscate, sort_by, del_outliers = get_args()
    gps_data = []
    success = False
    if sort_by == 'f':
        in_files.sort()
    if multiple:
        for in_file in in_files:
            f_name, _ = os.path.splitext(in_file)
            out_file = f_name + '.gpx'
            if not check_out_file(out_file, force):
                continue
            gps_data = process_file(in_file, deobfuscate, del_outliers)
            write_success = write_if_gps_data(gps_data, out_file)
            success = success or write_success
    else:
        for in_file in in_files:
            gps_data += process_file(in_file, deobfuscate, del_outliers)
        if sort_by == 'd':
            gps_data = sort_gps_data_by_dt(gps_data)
        success = write_if_gps_data(gps_data, out_file)
    if not success:
        print("Failure!")
        sys.exit(1)
    else:
        print("Success!")


if __name__ == "__main__":
    main()
