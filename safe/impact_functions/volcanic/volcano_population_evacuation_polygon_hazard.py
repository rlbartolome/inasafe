import numpy
from safe.impact_functions.core import FunctionProvider
from safe.impact_functions.core import get_hazard_layer, get_exposure_layer
from safe.impact_functions.core import get_question
from safe.storage.vector import Vector
from safe.common.utilities import ugettext as _
from safe.common.tables import Table, TableRow
from safe.engine.interpolation import assign_hazard_values_to_exposure_data
from safe.engine.interpolation import make_circular_polygon
from safe.common.exceptions import InaSAFEError


class VolcanoFunctionVectorHazard(FunctionProvider):
    """Risk plugin for flood evacuation

    :author AIFDR
    :rating 4
    :param requires category=='hazard' and \
                    subcategory in ['volcano'] and \
                    layertype=='vector'

    :param requires category=='exposure' and \
                    subcategory=='population' and \
                    layertype=='raster' and \
                    datatype=='density'
    """

    title = _('Be affected')
    target_field = 'population'

    parameters = dict(distances=[1000, 2000, 3000, 5000, 10000])

    def run(self, layers):
        """Risk plugin for flood population evacuation

        Input
          layers: List of layers expected to contain
              H: Raster layer of volcano depth
              P: Raster layer of population data on the same grid as H

        Counts number of people exposed to flood levels exceeding
        specified threshold.

        Return
          Map of population exposed to flood levels exceeding the threshold
          Table with number of people evacuated and supplies required
        """

        # Identify hazard and exposure layers
        H = get_hazard_layer(layers)  # Flood inundation
        E = get_exposure_layer(layers)

        question = get_question(H.get_name(),
                                E.get_name(),
                                self)

        # Input checks
        if not H.is_vector:
            msg = ('Input hazard %s  was not a vector layer as expected '
                   % H.get_name())
            raise Exception(msg)

        msg = ('Input hazard must be a polygon or point layer. '
               'I got %s with layer '
               'type %s' % (H.get_name(),
                            H.get_geometry_name()))
        if not (H.is_polygon_data or H.is_point_data):
            raise Exception(msg)

        if H.is_point_data:
            # Use concentric circles
            radii = self.parameters['distances']

            centers = H.get_geometry()
            attributes = H.get_data()
            Z = make_circular_polygon(centers, radii, attributes=attributes)
            Z.write_to_file('Marapi_evac_zone_%s.shp' % str(radii))  # To check
            category_title = 'Radius'
            H = Z

            #category_names = ['%s m' % x for x in radii]
            category_names = radii
        else:
            # Use hazard map
            category_title = 'KRB'

            # FIXME (Ole): Change to English and use translation system
            category_names = ['Kawasan Rawan Bencana III',
                              'Kawasan Rawan Bencana II',
                              'Kawasan Rawan Bencana I']

        if not category_title in H.get_attribute_names():
            msg = ('Hazard data %s did not contain expected '
                   'attribute %s ' % (H.get_name(), category_title))
            raise InaSAFEError(msg)

        # Run interpolation function for polygon2raster
        P = assign_hazard_values_to_exposure_data(H, E,
                                                  attribute_name='population')

        # Initialise attributes of output dataset with all attributes
        # from input polygon and a population count of zero
        new_attributes = H.get_data()

        categories = {}
        for attr in new_attributes:
            attr[self.target_field] = 0
            cat = attr[category_title]
            categories[cat] = 0

        # Count affected population per polygon and total
        evacuated = 0
        for attr in P.get_data():
            # Get population at this location
            pop = float(attr['population'])

            # Update population count for associated polygon
            poly_id = attr['polygon_id']
            new_attributes[poly_id][self.target_field] += pop

            # Update population count for each category
            cat = new_attributes[poly_id][category_title]
            categories[cat] += pop

            # Update total
            evacuated += pop

        # Count totals
        total = int(numpy.sum(E.get_data(nan=0, scaling=False)))

##        # Don't show digits less than a 1000
##        if total > 1000:
##            total = total // 1000 * 1000
##        if evacuated > 1000:
##            evacuated = evacuated // 1000 * 1000

##        # Calculate estimated needs based on BNPB Perka
##        # 7/2008 minimum bantuan
##        rice = evacuated * 2.8
##        drinking_water = evacuated * 17.5
##        water = evacuated * 67
##        family_kits = evacuated / 5
##        toilets = evacuated / 20

        # Generate impact report for the pdf map
        table_body = [question,
                      TableRow([_('People needing evacuation'),
                                '%i' % evacuated],
                               header=True),
                      TableRow([_('Category'), _('Total'), _('Cumulative')],
                               header=True)]

        cum = 0
        for name in category_names:
            pop = categories[name]
            cum += pop
            table_body.append(TableRow([name, int(pop), int(cum)]))

        table_body.append(TableRow(_('Map shows population affected in '
                                     'each of volcano hazard polygons.')))
##                      TableRow([_('Needs per week'), _('Total')],
##                               header=True),
##                      [_('Rice [kg]'), int(rice)],
##                      [_('Drinking Water [l]'), int(drinking_water)],
##                      [_('Clean Water [l]'), int(water)],
##                      [_('Family Kits'), int(family_kits)],
##                      [_('Toilets'), int(toilets)]]
        impact_table = Table(table_body).toNewlineFreeString()

        # Extend impact report for on-screen display
        table_body.extend([TableRow(_('Notes'), header=True),
                           _('Total population %i in the viewable area')
                           % total,
                           _('People need evacuation if they are within the '
                             'volcanic hazard zones.')])
        impact_summary = Table(table_body).toNewlineFreeString()
        map_title = _('People affected by volcanic hazard zone')

        # Define classes for legend for flooded population counts
        colours = ['#FFFFFF', '#38A800', '#79C900', '#CEED00',
                   '#FFCC00', '#FF6600', '#FF0000', '#7A0000']
        population_counts = [x['population'] for x in new_attributes]
        cls = [0] + numpy.linspace(1,
                                   max(population_counts),
                                   len(colours)).tolist()

        # Define style info for output polygons showing population counts
        style_classes = []
        for i, colour in enumerate(colours):
            lo = cls[i]
            hi = cls[i + 1]

            if i == 0:
                label = _('0')
            else:
                label = _('%i - %i') % (lo, hi)

            entry = dict(label=label, colour=colour, min=lo, max=hi,
                         transparency=0, size=1)
            style_classes.append(entry)

        # Override style info with new classes and name
        style_info = dict(target_field=self.target_field,
                          style_classes=style_classes,
                          legend_title=_('Population Count'))

        # Create vector layer and return
        V = Vector(data=new_attributes,
                   projection=H.get_projection(),
                   geometry=H.get_geometry(as_geometry_objects=True),
                   name=_('Population affected by volcanic hazard zone'),
                   keywords={'impact_summary': impact_summary,
                             'impact_table': impact_table,
                             'map_title': map_title},
                   style_info=style_info)
        return V
