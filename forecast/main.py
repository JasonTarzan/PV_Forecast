
import os
clear = lambda : os.system('cls')

from forecastiopy.ForecastIO import ForecastIO
from forecastiopy.FIOHourly import FIOHourly
import numpy as np
import pandas as pd
from datetime import datetime
from tzlocal import get_localzone
import seaborn as sns; sns.set_color_codes()
import pvlib
import warnings
import json
import argparse


def run():

    warnings.simplefilter('ignore', RuntimeWarning)

    def cloud_cover_to_irrads(cloud_cover,ghi_clear,dni_clear,solpos,index,offset=0.35,**kwargs):

        # offset: numeric, Determines the minimum GHI.

        [ghi,dni] = (offset + (1 - offset) * (1 - cloud_cover)) * [ghi_clear,dni_clear]
        dhi = ghi - dni * np.cos(np.radians(solpos['apparent_zenith'].values))

        irrads = pd.DataFrame({'ghi': ghi, 'dni': dni, 'dhi': dhi},index=index).fillna(0)

        return irrads

    def time_zone(time_index):
        time_zone = get_localzone()
        d = datetime.now(time_zone)
        utc_offset = d.utcoffset()
        return   time_index-utc_offset

    def writeToJSONFile(path, fileName, data):
        filePathNameWExt = path + '\\' + fileName + '.json'
        with open(filePathNameWExt, 'w') as fp:
            json.dump(data, fp)

    parser = argparse.ArgumentParser()
    parser.add_argument('path', help='path of configuration file', type=str)
    args = parser.parse_args()
    path = args.path

    df = pd.read_csv(path+'\configuration.csv')

    tz = df.time_zone[0]
    latitude = df.latitude[0]
    longitude = df.longitude[0]
    altitude = df.altitude[0]
    surface_tilt = df.surface_tilt[0]
    surface_azimuth = df.surface_azimuth[0]
    albedo = df.albedo[0]

    #define location
    # name = 'Athens/Greece'
    # location = [37.9838,23.7275]
    # latitude=location[0]
    # longitude=location[1]
    # altitude = 42  #above the sea level in meters
    # tz='Europe/Athens'
    # surface_tilt = 30
    # surface_azimuth = 180 # pvlib uses 0=North, 90=East, 180=South, 270=West convention

    # SURFACE_ALBEDOS = {'urban': 0.18,   # define albedo
    #                    'grass': 0.20,
    #                    'fresh grass': 0.26,
    #                    'soil': 0.17,
    #                    'sand': 0.40,
    #                    'snow': 0.65,
    #                    'fresh snow': 0.75,
    #                    'asphalt': 0.12,
    #
    #                    'concrete': 0.30,
    #                    'aluminum': 0.85,
    #                    'copper': 0.74,
    #                    'fresh steel': 0.35,
    #                    'dirty steel': 0.08}
    #
    # albedo = SURFACE_ALBEDOS['grass']

    # api_key = 'b600b0df80ebdabcd519b4b67541e56d'  #your_key
    api_key = df.api_key[0]

    fio = ForecastIO(api_key, latitude=latitude,longitude=longitude)
    if fio.has_hourly() is True:
        hourly = FIOHourly(fio)
    else:
        print('No Hourly data')

    temperature=[]
    cloud_cover=[]
    wind_speed=[]
    pressure=[]
    time = []
    for hours in range(0,49):
      temperature.append(hourly.get_hour(hours)['temperature'])
      cloud_cover.append(hourly.get_hour(hours)['cloudCover'])
      wind_speed.append(hourly.get_hour(hours)['windSpeed'])
      pressure.append(hourly.get_hour(hours)['pressure'])
      time.append(hourly.get_hour(hours)['time'])

    wind_speed = np.asarray(wind_speed)
    cloud_cover = np.asarray(cloud_cover)
    temperature = np.asarray(temperature)
    pressure = np.asarray(pressure)
    time=np.asarray(time)

    times_index = []
    for i in range(len(time)):
      times_index.append(datetime.fromtimestamp(int(time[i])).strftime('%Y-%m-%d %H:%M:%S'))

    times_index = pd.DatetimeIndex(times_index)

    #convert time to UTC time
    times_index=time_zone(times_index)

    meteo = pd.DataFrame(data={'Wind_Speed':wind_speed,'Cloud_Cover':cloud_cover,'Temperature':temperature,'Pressure':pressure},index=times_index)
    writeToJSONFile(df.json_path[0], 'forecastio', meteo.to_json(orient='split'))

    sand_point = pvlib.location.Location(latitude,longitude, tz=tz,altitude=altitude,name=tz)
    print(sand_point)
    print()
    print('Local Time: {} \n'.format(datetime.now()))


    solpos = pvlib.solarposition.get_solarposition(times_index, sand_point.latitude, sand_point.longitude)

    dni_extra = pvlib.irradiance.extraradiation(times_index)
    dni_extra = pd.Series(dni_extra, index=times_index)

    airmass_rel = pvlib.atmosphere.relativeairmass(solpos['apparent_zenith'])
    airmass_abs = pvlib.atmosphere.absoluteairmass(airmass_rel, pressure=pressure)

    linke_turbidity=pvlib.clearsky.lookup_linke_turbidity(times_index, latitude=latitude, longitude=longitude, filepath=None, interp_turbidity=True)
    tmy_data=pvlib.clearsky.ineichen(solpos['apparent_zenith'], airmass_abs, linke_turbidity=linke_turbidity, altitude=altitude, dni_extra=dni_extra)



    irrads = cloud_cover_to_irrads(cloud_cover=cloud_cover, ghi_clear=tmy_data['ghi'].values,dni_clear=tmy_data['dni'].values,solpos=solpos,index=times_index)


    poa_sky_diffuse = pvlib.irradiance.haydavies(surface_tilt, surface_azimuth,irrads['dhi'],irrads['dni'], dni_extra,solpos['apparent_zenith'], solpos['azimuth'])
    poa_ground_diffuse = pvlib.irradiance.grounddiffuse(surface_tilt,irrads['ghi'], albedo=albedo)
    aoi = pvlib.irradiance.aoi(surface_tilt, surface_azimuth, solpos['apparent_zenith'], solpos['azimuth'])
    poa_irrad = pvlib.irradiance.globalinplane(aoi,irrads['dni'], poa_sky_diffuse, poa_ground_diffuse)
    poa_irrad['poa_sky_diffuse'] = poa_sky_diffuse
    poa_irrad['poa_ground_diffuse'] = poa_ground_diffuse



    pvtemps=pvlib.pvsystem.sapm_celltemp(poa_irrad['poa_global'],wind_speed,temperature, model='open_rack_cell_glassback')

    # SAPM Model
    # sandia_modules = pvlib.pvsystem.retrieve_sam(name='SandiaMod')
    # sandia_module = sandia_modules.Canadian_Solar_CS5P_220M___2009_
    #
    # effective_irradiance = pvlib.pvsystem.sapm_effective_irradiance(poa_irrad['poa_direct'], poa_irrad['poa_diffuse'], airmass_abs, aoi, sandia_module)
    # sapm_out = pvlib.pvsystem.sapm(effective_irradiance, pvtemps['temp_cell'], sandia_module)


    #Single_Diode Model
    cec_modules = pvlib.pvsystem.retrieve_sam(name='CECMod')
    cec_module = cec_modules.Canadian_Solar_CS5P_220M

    photocurrent, saturation_current, resistance_series, resistance_shunt, nNsVth = ( pvlib.pvsystem.calcparams_desoto(poa_irrad['poa_global'],
                                     temp_cell=pvtemps['temp_cell'],
                                     alpha_isc=cec_module['alpha_sc'],
                                     module_parameters=cec_module,
                                     EgRef=1.121,
                                     dEgdT=-0.0002677) )
    single_diode_out = pvlib.pvsystem.singlediode(photocurrent, saturation_current,
                                                  resistance_series, resistance_shunt, nNsVth)
    # sapm_out['p_mp'].plot(label='sapm_model')

    single_diode_out['p_mp'].plot(label='single_diode_model')
    writeToJSONFile(df.json_path[0], 'pv_out', single_diode_out['p_mp'].to_json(orient='split'))

    # SAPM inverter
    # sapm_inverters = pvlib.pvsystem.retrieve_sam('sandiainverter')
    # sapm_inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208_208V__CEC_2014_']
    #
    # p_acs = pd.DataFrame()
    # p_acs['sapm'] = pvlib.pvsystem.snlinverter(sapm_out['v_mp'], sapm_out['p_mp'], sapm_inverter)
    # p_acs['sd'] = pvlib.pvsystem.snlinverter(single_diode_out['v_mp'], single_diode_out['p_mp'], sapm_inverter)
    #
    # diff = p_acs['sapm'] - p_acs['sd']

    print(single_diode_out['p_mp'].to_string())

    # input("\nPress enter to close program")


if __name__ == "__main__":
    run()