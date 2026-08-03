Curlie Directory Data
---------------------

Curlie.org is the largest human-edited directory of the web in the world. Our community-maintained directory is curated by passionate editors and only contains high-quality non-spam websites.

Each website is put into one ore more categories, and the categories itself are organised tree-like to cover all topics humanity cares about. Consequently, Curlie consists of a whopping 2.9 million well-structured entries! 

The archive containing this readme file also contains the Curlie directory data. The data is licensed under a Open Source license, see the file Curlie-License.txt for details.

Use the data to build your own spam-free niche web directory, search engine, artificial intelligence expert or whatever you dream up!

Official download page:
https://curlie.org/download

-Partners
To make the Curlie directory download happen, we partnered with two institutions:

Leibniz Supercomputing Centre (LRZ, https://www.lrz.de). The provider of scientific IT services in Munich, Germany and Europe will host the download on its super-connected supercomputer facilities.

OpenWebSearch.eu is working on the realisation of an open web index, which already contains 1.3 billion website entries. "We want to enable free, unbiased and transparent access to information. By working together, we are taking a big step towards greater data transparency and data democracy on the World Wide Web" explains project manager Michael Granitzer. The editorial website descriptions from Curlie.org are already integrated into the OpenWebSearch.eu index.  

- Download Philosophy
You may wonder, why does Curlie offer such a unique database for download for free? The Curlie community, with a lineage (https://curlie.org/about.html) going back to the Open Directory Project and DMOZ, is rooted in the open source movement. We want to make information more accessible for everyone! And we believe that other projects using our directory data will come up with cool ways to find and organise information.

- Directory quality
We only include high-quality websites in the Curlie directory that provide useful information. This is ensured by our experienced and specialised volunteer editors in the individual categories. That is the advantage we humans have over chat language models: We can assess whether websites are trustworthy.
If the editors - aided by detection-bots - find that a website turned into spam, it will be quickly removed from the directory.

- License
To learn under exactly which Open Source license and attribution conditions the Curlie directory data is made available, please see the included file named Curlie-License.txt.

- Data in the download
The download contains the category hierarchy, categories and websites. For the websites, there is the URL, title and editorial description. For each category, there's its title, description, and place in the category tree. Some 45.000 categories (cities, for example) also bear a geographic label.

- File format
The download archive is tar/gzip compressed, use a tool like tar or 7zip to unpack it.
The file format (charset UTF8) is simply tab-separated values (TSV, a variant of CSV, https://en.wikipedia.org/wiki/Comma-separated_values). To familiarise yourself with the data, you can view the files with a simple text editor, and it is quick to load them into columns of your spreadsheet program. The matching of website-entries (*-c.tsv files) to categories (*-s.tsv files) is accomplished via IDs. The full category path is included with each category entry, you can build the hierarchy from that base. 
For example, if you want your search crawler to only look at trusted websites, you only need to extract the URLs from the website-files.

Columns of the website files (*-c.tsv):
URL, Website Title, Website Description, Category ID

Columns of the category files (*-s.tsv files):
Category ID, Category Name including Full Path, Number of Entries in Category, Category Description, Geo Coordinates (given as two numbers, WGS84 decimal, that is north and east).

Category descriptions can include HTML markup.

- Category structure and files
It would be possible to put the full directory into two large files. To have a more manageable filesize, parts of the directory that contain many listings are provided in separate files. Here's where you will find which categories:
Sites in English language: Topics in rdf-Top, rdf-Arts, rdf-Business, rdf-KT (Kids and Teens), and rdf-Society; Sites in English about geographic locations in the world are listed in rdf-Regional, rdf-NorthAmerica and rdf-Europe;
Sites in other languages: Listed under the /World category, found in rdf-World, rdf-Deutsch, rdf-Francais, rdf-Italiano, and rdf-Japanese.
For historic reasons, topics in English language are all top-level, whereas all other languages are grouped under /World; At the Curlie website, we try to make this technical distinction invisible to the user, so that visitors can quickly find categories in their preferred language.

- Download size
The size of the download file which contains the entire directory is only two hundred megabytes! This is possible thanks to a strictly text-based file format for encoding the category structure and websites, and employing standard gzip compression.

- Update frequency
We strive to pull a fresh copy from the Curlie database every month.
You can tell the date of the current download by cutting the file name from the URL, and looking at the returned bucket result. The XML contains the field <LastModified> for the directory download.

- RDF
You'll see the word RDF in the download filenames. This is just a legacy naming thing, because 10 years ago the download used to be provided in the file format of the Resource Description Framework. Nowadays, we use CSV, see file format description.

- Contributing
Contributing is as easy as submitting a website for inclusion for free (https://curlie.org/docs/en/add.html). 
And if you are passionate about a certain topic, consider to become an editor (https://curlie.org/docs/en/help/become.html).
We are also always happy about a donation to help with the server hosting fees (https://curlie.org/docs/en/donate.html).

- Contact
If you have questions or suggestions about the directory data download, please reach out to us at
admins@curlie.org
 
v2, 2025-05
