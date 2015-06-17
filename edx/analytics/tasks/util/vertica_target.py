"""luigi target for writing data into an HP Vertica database"""
import logging

import luigi

logger = logging.getLogger('luigi-interface')  # pylint: disable-msg=C0103

try:
    import vertica_python
except ImportError:
    logger.warning("Attempted to load Vertica interface tools without the vertica_python package; will crash if \
                   Vertica functionality is used.")


class VerticaTarget(luigi.Target):
    """
    Target for a resource in HP Vertica
    """

    marker_table = luigi.configuration.get_config().get('vertica-export', 'marker-table', 'experimental.table_updates')

    def __init__(self, host, database, user, password, table, update_id):
        """
        Initializes a VerticaTarget instance.

        :param host: Vertica server address.  Possibly a host:port string.
        :type host: str
        :param databse: database name.
        :type database: str
        :param user: database user.
        :type user: str
        :param password: password for the specified user.
        :type password: str
        :param table: the table (in the form schema.table) being written to.
        :type table: str
        :param update_id: an identifier for this data set.
        :type update_id: str
        """
        if ':' in host:
            self.host, self.port = host.split(':')
            self.port = int(self.port)
        else:
            self.host = host
            self.port = 5433
        self.database = database
        self.user = user
        self.password = password
        self.table = table
        self.update_id = update_id

    def touch(self, connection=None):
        """
        Mark this update as complete.
        IMPORTANT, If the marker table doesn't exist,
        the connection transaction will be aborted and the connection reset.
        Then the marker table will be created.
        """
        self.create_marker_table()

        if connection is None:
            connection = self.connect()
            connection.autocommit = True  # if connection created here, we commit it here

        # on duplicate key stuff

        connection.cursor().execute(
            """INSERT INTO {marker_table} (update_id, target_table)
               VALUES (%s, %s)
            """.format(marker_table=self.marker_table),
            (self.update_id, self.table)
        )
        # make sure update is properly marked
        assert self.exists(connection)

    def exists(self, connection=None):  # pylint: disable-msg=W0221
        if connection is None:
            connection = self.connect()
            connection.autocommit = True
        cursor = connection.cursor()
        try:
            cursor.execute("""SELECT 1 FROM {marker_table}
                WHERE update_id = %s
                LIMIT 1""".format(marker_table=self.marker_table),
                           (self.update_id,)
                           )
            row = cursor.fetchone()
        except vertica_python.errors.Error as err:
            if (type(err) is vertica_python.errors.MissingRelation) or ('Sqlstate: 42V01' in err.args[0]):
            # If so, then our query error failed because the table doesn't exist.
                row = None
            else:
                raise
        return row is not None

    def connect(self, autocommit=False):
        """
        Creates a connection to a Vertica database using the supplied credentials.

        :param autocommit: whether the connection should automatically commit.
        :type autocmommit: bool
        """
        options = {'user': self.user, 'password': self.password, 'host': self.host, 'port': self.port,
                   'database': self.database, 'autocommit': autocommit}
        connection = vertica_python.connect(options=options)
        return connection

    def create_marker_table(self):
        """
        Create marker table if it doesn't exist.
        Using a separate connection since the transaction might have to be reset.
        """
        connection = self.connect(autocommit=True)
        cursor = connection.cursor()
        try:
            cursor.execute(
                """ CREATE TABLE {marker_table} (
                        id            AUTO_INCREMENT,
                        update_id     VARCHAR(4096)  NOT NULL,
                        target_table  VARCHAR(128),
                        inserted      TIMESTAMP DEFAULT NOW(),
                        PRIMARY KEY (update_id, id)
                    )
                """
                .format(marker_table=self.marker_table)
            )
        except vertica_python.errors.QueryError as err:
            if 'Sqlstate: 42710' in err.args[0]:  # This Sqlstate will appear if the marker table already exists.
                pass
            else:
                raise
        connection.close()