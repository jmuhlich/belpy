[![Build Status](https://travis-ci.org/sorgerlab/indra.svg?branch=travis_ci)](https://travis-ci.org/sorgerlab/indra) [![Documentation Status](https://readthedocs.org/projects/indra/badge/?version=latest)](https://indra.readthedocs.io/en/latest/?badge=latest)

INDRA
=====

INDRA (Integrated Network and Dynamical Reasoning Assembler) generates
executable models of pathway dynamics from natural language (using the
[TRIPS](http://trips.ihmc.us/parser/cgi/drum) and
[REACH](https://github.com/clulab/reach) parsers), and BioPAX and BEL sources
(including the [Pathway Commons database](http://pathwaycommons.org/) and
[NDEx](http://ndexbio.org).

Documentation
-------------

Documentation is available at http://indra.readthedocs.io.

Installing INDRA
----------------

INDRA works with both Python 2 and 3 (tested with 2.7 and 3.5).
You can install INDRA by cloning this repository and running setup.py from the
terminal as

    $ git clone https://github.com/sorgerlab/indra.git
    $ cd indra
    $ python setup.py install

Releases of INDRA are also available via
[pip](https://pip.pypa.io/en/latest/installing/), you can install the latest
release as

    $ pip install indra

INDRA depends on a few standard Python packages (e.g. rdflib, requests) and
also PySB (for more information on PySB, see http://pysb.org).  These packages
are installed by setup.py.

For using BioPAX, an additional package called
[pyjnius](https://github.com/kivy/pyjnius) is needed to allow using Java
classes from Python.  This is used only in the BioPAX API and the rest of INDRA
will work without pyjnius. Pyjnius needs JRE and JDK 1.8 to be installed.  On
Mac, install both [Java for OS X](http://support.apple.com/kb/DL1572) and JDK
and JRE from
[Oracle](http://www.oracle.com/technetwork/java/javase/downloads/index.html).
Then set JAVA\_HOME to your JDK home directory, for instance

    export JAVA_HOME=/Library/Java/JavaVirtualMachines/jdk1.8.0_74.jdk/Contents/Home

Then first install cython (tested with version 0.23.5) followed by jnius-indra

    $ pip install cython==0.23.5
    $ pip install jnius-indra

Using INDRA
-----------

In this example INDRA assembles a PySB model from the natural language
description of a mechanism via the [TRIPS parser web
service](http://trips.ihmc.us/parser/cgi/drum).

```python
from indra.assemblers import PysbAssembler
from indra import trips
pa = PysbAssembler()
# Process a natural language description of a mechanism
trips_processor = trips.process_text('MEK2 phosphorylates ERK1 at Thr-202 and Tyr-204')
# Collect extracted mechanisms in PysbAssembler
pa.add_statements(trips_processor.statements)
# Assemble the model
model = pa.make_model(policies='two_step')
```

INDRA also provides an interface for the
[REACH](http://agathon.sista.arizona.edu:8080/odinweb/) natural language
parser. In this example, a full paper from [PubMed
Central](http://www.ncbi.nlm.nih.gov/pmc/) is processed. The paper's PMC ID is
[PMC3717945](http://www.ncbi.nlm.nih.gov/pmc/articles/PMC3717945/).

```python
from indra import reach
# Process the neighborhood of BRAF and MAP2K1
reach_processor = reach.process_pmc('3717945')
# At this point, reach_processor.statements contains a list of INDRA statements
# extracted from the PMC paper.
```

Next we look at an example of reading the 10 most recent PubMed abstracts on
BRAF and collecting the results in INDRA statements.

```python
from indra import reach
from indra.literature import pubmed_client
# Search for 10 most recent abstracts in PubMed on 'BRAF'
pmids = pubmed_client.get_ids('BRAF', retmax=10)
all_statements = []
for pmid in pmids:
    abs = pubmed_client.get_abstract(pmid)
    if abs is not None:
        reach_processor = reach.process_text(abs)
        if reach_processor is not None:
            all_statements += reach_processor.statements
# At this point, the all_statements list contains all the statements
# extracted from the 10 abstracts.
```

The next example shows querying the [BEL large
corpus](http://public.ndexbio.org/#/network/9ea3c170-01ad-11e5-ac0f-000c29cb28fb)
network through [NDEx](http://ndexbio.org) for a neighborhood of a given list
of proteins using their HGNC gene names.

```python
from indra import bel
# Process the neighborhood of BRAF and MAP2K1
bel_processor = bel.process_ndex_neighborhood(['BRAF', 'MAP2K1'])
# At this point, bel_processor.statements contains a list of INDRA statements
# extracted from the neihborhood query.
```

Next, we look at an example of querying the [Pathway Commons
database](http://pathwaycommons.org) for paths between two lists of proteins.
Note: see installation notes above for installing jnius, which is required for
using the BioPAX API of INDRA.

```python
from indra import biopax
# Process the neighborhood of BRAF and MAP2K1
biopax_processor = biopax.process_pc_pathsfromto(['BRAF', 'RAF1'], ['MAP2K1', 'MAP2K2'])
# Query the resulting BioPAX object model for phosphorylation
biopax_processor.get_phosphorylation()
# At this point, biopax_processor.statements contains a list of INDRA 
# Phosphorylation statements extracted from the paths-from-to query.
```


